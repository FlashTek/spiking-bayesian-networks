import numpy as np
from matplotlib import pyplot as plt
import utility as ut
import network as nt
from tqdm import tqdm as tqdm
import plot as pt
from collections import deque # fifo structure for history



image_duration = 0.250    # [s]
mnist_px_samples = None
current_image_px = None
current_image_id = None
current_image_t = -1      # [units of image_duration]
current_time = 0.0        # [s]

# mnist
labels = [0, 1]
def init_mnist():
    (x_train, y_train), (x_test, y_test) = ut.mnist.load_data()
    selection = [y_test == label for label in labels]

    minimum_length = min(np.sum(selection, axis=1))
    selection = np.any([np.all((item, np.cumsum(item) < minimum_length), axis=0) for item in selection], axis=0)
    X = x_test[selection]
    Y = y_test[selection]
    X = X.reshape((len(X), -1)) / 255.0
    global mnist_px_samples
    mnist_px_samples = (X > 0.5).astype(np.float32)


def get_input_at_time(t):
    """
        which input image is shown at time t
        updates current image, only works for consecutive t

        Parameters
        ----------
        t : float
            time in seconds
    """

    global current_image_t
    global current_image_id
    global current_image_px

    assert t >= current_image_t * image_duration, "don't travel back in time"

    if t / image_duration > current_image_t + 1:
        current_image_t = np.floor(t / image_duration)
        current_image_id = np.random.randint(0, len(mnist_px_samples))
        current_image_px = mnist_px_samples[current_image_id]

    return current_image_px



def init_z_plot(net):
    assert net._history_duration > 0, "need a history to plot"
    fig, ax = plt.subplots()
    ax = plt.axes(xlim=(-net._history_duration, 0),
        ylim=(-.5, net._n_outputs-.5))
    scat = ax.scatter([], [], s=10)

    return fig, ax, scat

def plot_z_history(net, scat):
    # print(list(zip(t_hist, z_hist)))
    dat = np.array(list(zip(net._t_hist, net._z_hist)))
    dat[:,0] = dat[:,0] - current_time
    # print(dat)
    # dat = np.array(net._t_hist)-net._history_duration
    # dat = np.hstack((dat, np.array(net._z_hist)))
    # print(dat.shape)
    # exit()
    # dat = np.array(list(zip(net._t_hist, net._z_hist)))
    scat.set_offsets(dat)
    return scat,




class EventBinaryWTANetwork():
    """

    Eventbased mplementation of the (soft) Winner Takes All (WTA) network,
    assuming Bernoulli distributions
    """

    def __init__(self, n_inputs, n_outputs, delta_T, r_net, m_k, eta_v, eta_b,
        history_duration = 0):
        """
            Parameters
            ----------
            delta_T : float
                numeric integration time step size

            r_net : float
                global target firing rate of the whole network [1/s]

            m_k :  numpy.ndarray
                size n_outputs
                has to sum up to one, propto relative target firing rate of
                neuron k

            eta_v : float
                learning rate of v eq (8)

            eta_b : float
                learing rate of b eq. (7)

            history_duration : float
                how long [s] to store input and output history
        """

        self._n_inputs = n_inputs
        self._n_outputs = n_outputs
        self._delta_T = delta_T
        self._r_net = r_net
        self._m_k = m_k
        self._eta_v = eta_v
        self._eta_b = eta_b
        self._history_duration = history_duration
        self._z_hist = deque([])  # index k of spiking output neuron z
        self._t_hist = deque([])  # time float of spike
        self._y_hist = deque([])  # mnist sample id of input

        if np.isscalar(self._m_k):
            self._m_k = np.ones((n_outputs, 1)) * self._m_k

        assert len(self._m_k) == n_outputs, "Length of m_ks does not match number of output neurons"

        self._V = np.random.normal(scale=1e-3, size=(self._n_outputs, self._n_inputs))
        self._b = np.zeros((self._n_outputs, 1))
        # output spike count to get spikes per second
        self._z_spikes = np.zeros(self._n_outputs)

    def next_spike_time(self):
        """
            Return next spike time from poisson process with rate r_net
        """
        return - np.log(np.random.uniform())/self._r_net

    def step(self):
        global current_time
        isi =  - np.log(np.random.uniform())/self._r_net
        inputs = get_input_at_time(current_time + isi)
        inputs = inputs.reshape((-1, 1))
        assert len(inputs) == self._n_inputs, "Input length does not match"

        # u = V * input + b
        u = np.dot(self._V, inputs) + self._b

        z = np.zeros((self._n_outputs, 1))

        # p \propto softmax(u); eq. (4)
        # p_z = np.exp(u) / np.sum(np.exp(u) + 1e-8) * self._delta_T * self._r_net
        p_z = np.exp(u) / np.sum(np.exp(u) + 1e-8)

        # erm so this is needed cos event based i guess
        # p_z = p_z / np.sum(p_z)


        # sample from softmax distribution, i.e. choose a single neuron to spike
        sum_p_z = np.cumsum(p_z)
        diff = sum_p_z - np.random.uniform(0, 1, 1) > 0
        k = np.argmax(diff)

        # print(p_z, np.sum(p_z), sum_p_z)
        if diff[k]:
            z[k] = 1.0
            self._z_spikes[k] += 1

        self._b += self._eta_b * \
            (isi * self._r_net * self._m_k - ut.dirac(z - 1))
        self._V += self._eta_v * ut.dirac(z - 1) * \
            (inputs.T - ut.sigmoid(self._V))

        current_time = current_time + isi

        # update history stuff
        if self._history_duration > 0:
            self._t_hist.append(current_time)
            self._z_hist.append(k)
            self._y_hist.append(current_image_id)
            while len(self._t_hist) > 1 \
            and self._t_hist[0] < current_time - self._history_duration:
                self._t_hist.popleft()
                self._z_hist.popleft()
                self._y_hist.popleft()

        return z

def update_steps(steps=1000, imshows=None, fig=None):
    pbar = tqdm(range(steps))
    for i in pbar:
        z = net.step()[:,0]
        # plotting every percent
        if not i % int(steps/100):
            # reshape to 28x28 to plot
            weights = net._V.reshape((-1, 28, 28))
            if fig is not None:
                for i in range(len(imshows)):
                    imshows[i].set_data(ut.sigmoid(weights[i]))

                fig.canvas.draw()
                fig.canvas.flush_events()

                plot_z_history(net, scat_hist)
                fig_hist.canvas.draw()
                fig_hist.canvas.flush_events()

                out = ''
                for i in net._z_spikes:
                    out += f'{i/current_time:.3f} '
                pbar.set_description(out)



delta_T = 1e-3
n_outputs = 12
n_inputs = 28*28
r_net = 50.0 # 0.5
m_k = 1.0/n_outputs

if __name__ == '__main__':
    init_mnist()
    get_input_at_time(0)
    net = EventBinaryWTANetwork(n_inputs=n_inputs, n_outputs=n_outputs,
        delta_T=delta_T, r_net=r_net, m_k=m_k, eta_v=1e-4, eta_b=1e-1,
        history_duration=2)

    # weight figures
    fig = plt.figure(figsize=(3.5, 1.16), dpi=300)
    plt.show(block=False)
    axes = pt.add_axes_as_grid(fig, 2, 6, m_xc=0.01, m_yc=0.01)
    imshows = []
    for i, ax in enumerate( list(axes.flatten()) ):
        # disable legends
        ax.set_yticks([])
        ax.set_xticks([])
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.spines['bottom'].set_visible(False)

        imshows.append(ax.imshow(ut.sigmoid(net._V[i].reshape((28, 28))),
            vmin=0.3, vmax=.7))
    fig.canvas.draw()
    fig.canvas.flush_events()

    fig_hist, ax_hist, scat_hist = init_z_plot(net)

    update_steps(int(1e5), imshows, fig)

