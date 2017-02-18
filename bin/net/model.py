# -*- coding: utf-8 -*-
import sys
import chainer
import chainer.functions as F
import chainer.links as L
import numpy as np
from chainer import cuda, Function, Variable, reporter
from chainer import Link, Chain
from chainer import reporter

"""
TODO:
* Kernel size other than k==2
* Perplexity
"""


class QRNNLayer(Chain):
    def __init__(self, in_size, out_size, conv_width=2):
        self.in_size = in_size
        self.out_size = out_size

        if conv_width == 2:
            super(QRNNLayer, self).__init__(
                W = L.Linear(in_size=in_size, out_size=3*out_size, nobias=True),
                V = L.Linear(in_size=in_size, out_size=3*out_size)
            )
            self.pad_vector = Variable(self.xp.zeros((1, self.in_size), dtype=self.xp.float32), volatile='AUTO')
        else:
            print("未実装")
            raise NotImplementedError

    def __call__(self, c, xs, train=True):
        """
        The API is (almost) equivalent to NStepLSTM's.
        Just pass the list of variables, and they get encoded.
        """
        inds = np.argsort([-len(x.data) for x in xs]).astype('i')
        xs = [xs[i] for i in inds]
        pool_in = self.convolution(xs)
        hs = self.pooling(c, pool_in, train)

        # permutate the list back
        ret = [None] * len(inds)
        for i, idx in enumerate(inds):
            ret[idx] = hs[i]
        return ret

    def convolution(self, xs):
        x_len = [x.shape[0] for x in xs]
        split_inds = [sum(x_len[:i]) + x for i, x in enumerate(x_len)][:-1]

        xs_prev = [F.concat([self.pad_vector, x[:-1,:]], axis=0) for x in xs]
        xs_prev = F.concat(xs_prev, axis=0)
        xs = F.concat(xs, axis=0)
        conv_output = self.W(xs_prev) + self.V(xs)

        ret = F.transpose_sequence(F.split_axis(conv_output, split_inds, axis=0))
        return ret

    def pooling(self, c, xs, train):
        """
        implement fo-pooling
        (seemingly the best option when compared to ifo/f-pooling)
        """
        c_prev = c
        hs = []
        for x in xs:
            w0, w1, w2 = F.split_axis(x, 3, axis=1)
            z = F.tanh(w0)
            f = F.sigmoid(w1)
            o = F.sigmoid(w2)
            if c_prev is None:
                c = (1 - f) * z
            else:
                c_prev = c_prev[:z.shape[0],:]
                if train:
                    zoneout_mask = (0.1 < self.xp.random.rand(*f.shape))
                    c = f * c_prev + (1 - f) * z * zoneout_mask
                else:
                    c = f * c_prev + (1 - f) * z
            h = o * c
            hs.append(h)
            c_prev = c
        return F.transpose_sequence(hs)

class QRNNLangModel(Chain):
    def __init__(self, n_vocab, embed_dim, out_size, conv_width=2, train=True):
        self.embed_dim = embed_dim
        super(QRNNLangModel, self).__init__(
            embed = L.EmbedID(in_size=n_vocab, out_size=embed_dim),
            qrnn = QRNNLayer(in_size=embed_dim, out_size=out_size),
            l1 = L.Linear(in_size=out_size, out_size=n_vocab)
        )
        self.train = train

    def __call__(self, *args):
        xs = args
        emx = [self.embed(x) for x in xs]
        hs = self.qrnn(c=None, xs=emx, train=self.train)
        ys = [self.l1(h) for h in hs]
        return ys
