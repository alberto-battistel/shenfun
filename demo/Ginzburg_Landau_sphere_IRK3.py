"""
Solve the Ginzburg-Landau equation on a sphere

    u_t = div(grad(u)) + u - (1+1.5i)*u*|u|**2

We use an implicit third order Runge-Kutta method for the time-integration.

"""
from shenfun import *
from mayavi import mlab
import sympy as sp

show = mayavi_show()

theta, phi = psi = sp.symbols('x,y', real=True, positive=True)
tt = sp.Symbol('t', real=True, positive=True)


class GinzburgLandau(IRK3):
    def __init__(self, N=(32, 64), dt=0.25, refineplot=False,
                 modplot=100, modsave=1e8, filename='GL',
                 family='C', quad='GC'):
        self.dt = dt
        self.N = np.array(N)
        self.modplot = modplot
        self.modsave = modsave
        self.refineplot = refineplot

        # Define spherical coordinates
        r = 50
        rv = (r*sp.sin(theta)*sp.cos(phi), r*sp.sin(theta)*sp.sin(phi), r*sp.cos(theta))

        # Regular spaces
        L0 = self.L0 = FunctionSpace(N[0], family, domain=(0, np.pi), dtype='D')
        F1 = self.F1 = FunctionSpace(N[1], 'F', dtype='D')
        T = self.T = TensorProductSpace(comm, (L0, F1), dtype='D', coordinates=(psi, rv, sp.Q.positive(sp.sin(theta))))

        self.Tp = self.T.get_dealiased((1.5, 1.5))
        self.u_hat = Function(self.T)
        self.ub = Array(self.T)
        self.up = Array(self.Tp)
        self.T2 = self.T.get_refined(2*self.N)
        self.T3 = self.T.get_refined([2*N[0], 2*N[1]+1]) # For wrapping around
        self.u2_hat = Function(self.T2)
        if self.refineplot not in (False, 1):
            self.ur_hat = Function(self.T.get_refined(self.refineplot*self.N))
        self.ub2 = Array(self.T2)
        self.ub3 = Array(self.T3)

        # Result and checkpoint data
        thetaj, phij = self.T2.mesh(uniform=True)
        phij = np.hstack([phij, phij[:, 0][:, None]])
        self.file_u = HDF5File(filename+'_U.h5', domain=[np.squeeze(d) for d in [thetaj, phij]], mode='a')
        self.file_c = HDF5File(filename+'_C.h5', domain=self.T.mesh(), mode='w')

        IRK3.__init__(self, T)

    def LinearRHS(self, u):
        return u + div(grad(u))

    def NonlinearRHS(self, u, u_hat, rhs, **par):
        v = TestFunction(self.T)
        up = self.Tp.backward(self.u_hat, self.up)
        rhs[:] = 0
        w0 = self.Tp.forward(-(1+1.5j)*up*abs(up)**2, self.w0)
        rhs = self.mass.matvec(w0, rhs)
        return rhs

    def initialize(self):
        sph = sp.functions.special.spherical_harmonics.Ynm
        self.ub = Array(self.T, buffer=sph(6, 3, theta, phi))
        self.ub.imag[:] = 0
        #self.ub = Array(self.T, buffer=theta)
        self.u_hat = self.ub.forward(self.u_hat)
        self.init_plots()

    def init_plots(self):
        u2_hat = self.u_hat
        if self.refineplot not in (False, 1):
            u2_hat = self.u_hat.refine(self.refineplot*self.N)

        ur = u2_hat.backward(uniform=True)
        X = u2_hat.function_space().local_curvilinear_mesh(uniform=True)
        X[0] = np.hstack([X[0], X[0][:, 0][:, None]])
        X[1] = np.hstack([X[1], X[1][:, 0][:, None]])
        X[2] = np.hstack([X[2], X[2][:, 0][:, None]])
        ur = np.hstack([ur, ur[:, 0][:, None]])
        self.X = x, y, z = X
        mlab.figure(bgcolor=(1, 1, 1), size=(600, 600))
        self.s = mlab.mesh(x, y, z, scalars=ur.real, colormap='jet')
        show()

    def plot(self, t, tstep, u_hat=None):
        u_hat = self.u_hat if u_hat is None else u_hat
        u2_hat = u_hat
        if self.refineplot not in (False, 1):
            u2_hat = u_hat.refine(self.refineplot*self.N, output_array=self.ur_hat)
        ur = u2_hat.backward(uniform=True)
        ur = np.hstack([ur, ur[:, 0][:, None]])
        self.s.mlab_source.set(scalars=ur.real)
        show()

    def quiver_gradient(self):
        """
        Plot the gradient vector in current window.

        This requires to cast the contravariant vector components into
        Cartesian components first.
        """
        TV = VectorTensorProductSpace(self.T)
        du = project(grad(self.u_hat), TV).backward(uniform=True).real # Contravariant components (real part)
        b = self.T.coors.b
        ui, vi = self.T.local_mesh(broadcast=True, uniform=True)
        b1 = np.array(sp.lambdify(psi, b[0])(ui, vi))
        b2 = sp.lambdify(psi, b[1])(ui, vi)
        b2[2] = np.zeros(ui.shape) # b2[2] is 0, so need to broadcast
        b2 = np.array(b2)
        df = du[0]*b1 + du[1]*b2   # Cartesian components
        df = np.concatenate([df, df[:, :, 0][:, :, None]], axis=2) # wrap periodic
        X = self.T.local_curvilinear_mesh(uniform=True)
        X[0] = np.hstack([X[0], X[0][:, 0][:, None]])
        X[1] = np.hstack([X[1], X[1][:, 0][:, None]])
        X[2] = np.hstack([X[2], X[2][:, 0][:, None]])
        x, y, z = X
        mlab.quiver3d(x[::2, ::2], y[::2, ::2], z[::2, ::2], df[0, ::2, ::2], df[1, ::2, ::2], df[2, ::2, ::2],
                      color=(0, 0, 0), scale_factor=5, mode='2darrow')
        show()

    def tofile(self, tstep):
        self.u2_hat = self.u_hat.refine(2*self.N, output_array=self.u2_hat)
        ub2 = self.u2_hat.backward(self.ub2, uniform=True)
        self.ub3[:] = np.hstack([ub2, ub2[:, 0][:, None]])
        self.file_u.write(tstep, {'u': [self.ub3.real]})
        self.file_c.write(0, {'u': [self.u_hat]})

    def update(self, u, u_hat, t, tstep, **par):
        if tstep % self.modsave == 0:
            self.tofile(tstep)
            print('Time %2.4f'%(t), 'Energy %2.6e'%(dx(abs(self.ub2**2))))

        if tstep % self.modplot == 0:
            self.plot(t, tstep)

if __name__ == '__main__':
    from time import time
    from mpi4py_fft import generate_xdmf
    t0 = time()
    d = {
        'N': (128, 256),
        'refineplot': 2,
        'dt': 0.2,
        'filename': 'GLMR128_256A',
        'modplot': 10,
        'modsave': 10,
        'family': 'C',
        'quad': 'GC'
        }
    c = GinzburgLandau(**d)
    c.initialize()
    c.solve(c.ub, c.u_hat, c.dt, (0, 500))
    print('Computing time %2.4f'%(time()-t0))
    if comm.Get_rank() == 0:
        generate_xdmf('_'.join((d['filename'], 'U'))+'.h5')
