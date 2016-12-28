from __future__ import absolute_import, division, print_function
from collections import OrderedDict

import numpy as np
import tensorflow as tf


class ConvNet(object):
    """Basic implementation of ConvNet class compatible with tfutils.
    """

    def __init__(self, seed=None, **kwargs):
        self.seed = seed
        self.output = None
        self._params = OrderedDict()

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, value):
        name = tf.get_variable_scope().name
        if name not in self._params:
            self._params[name] = OrderedDict()
        self._params[name][value['type']] = value

    @property
    def graph(self):
        return tf.get_default_graph().as_graph_def()

    def initializer(self, kind='xavier', stddev=.01):
        if kind == 'xavier':
            init = tf.contrib.layers.initializers.xavier_initializer(seed=self.seed)
        elif kind == 'trunc_norm':
            init = tf.truncated_normal_initializer(mean=0, stddev=stddev, seed=self.seed)
        else:
            raise ValueError('Please provide an appropriate initialization '
                             'method: xavier or trunc_norm')
        return init

    @tf.contrib.framework.add_arg_scope
    def conv(self,
             out_shape,
             ksize=3,
             stride=1,
             padding='SAME',
             init='xavier',
             stddev=.01,
             bias=1,
             activation='relu',
             weight_decay=None,
             in_layer=None):
        if in_layer is None: in_layer = self.output
        if weight_decay is None: weight_decay = 0.
        in_shape = in_layer.get_shape().as_list()[-1]

        if isinstance(ksize, int):
            ksize1 = ksize
            ksize2 = ksize
        else:
            ksize1, ksize2 = ksize

        kernel = tf.get_variable(initializer=self.initializer(init, stddev=stddev),
                                 shape=[ksize1, ksize2, in_shape, out_shape],
                                 dtype=tf.float32,
                                 regularizer=tf.contrib.layers.l2_regularizer(weight_decay),
                                 name='weights')
        conv = tf.nn.conv2d(in_layer, kernel,
                            strides=[1, stride, stride, 1],
                            padding=padding)
        biases = tf.get_variable(initializer=tf.constant_initializer(bias),
                                 shape=[out_shape],
                                 dtype=tf.float32,
                                 name='bias')
        self.output = tf.nn.bias_add(conv, biases, name='conv')
        if activation is not None:
            self.output = self.activation(kind=activation)
        self.params = {'input': in_layer.name,
                       'type': 'conv',
                       'num_filters': out_shape,
                       'stride': stride,
                       'kernel_size': (ksize1, ksize2),
                       'padding': padding,
                       'init': init,
                       'stddev': stddev,
                       'bias': bias,
                       'activation': activation,
                       'weight_decay': weight_decay,
                       'seed': self.seed}
        return self.output

    @tf.contrib.framework.add_arg_scope
    def fc(self,
           out_shape,
           init='xavier',
           stddev=.01,
           bias=1,
           activation='relu',
           dropout=.5,
           in_layer=None):
        if in_layer is None: in_layer = self.output
        resh = tf.reshape(in_layer,
                          [in_layer.get_shape().as_list()[0], -1],
                          name='reshape')
        in_shape = resh.get_shape().as_list()[-1]

        kernel = tf.get_variable(initializer=self.initializer(init, stddev=stddev),
                                 shape=[in_shape, out_shape],
                                 dtype=tf.float32,
                                 name='weights')
        biases = tf.get_variable(initializer=tf.constant_initializer(bias),
                                 shape=[out_shape],
                                 dtype=tf.float32,
                                 name='bias')
        fcm = tf.matmul(resh, kernel)
        self.output = tf.nn.bias_add(fcm, biases, name='fc')
        if activation is not None:
            self.activation(kind=activation)
        if dropout is not None:
            self.dropout(dropout=dropout)

        self.params = {'input': in_layer.name,
                       'type': 'fc',
                       'num_filters': out_shape,
                       'init': init,
                       'bias': bias,
                       'stddev': stddev,
                       'activation': activation,
                       'dropout': dropout,
                       'seed': self.seed}
        return self.output

    @tf.contrib.framework.add_arg_scope
    def norm(self,
             depth_radius=2,
             bias=1,
             alpha=2e-5,
             beta=.75,
             in_layer=None):
        if in_layer is None: in_layer = self.output
        self.output = tf.nn.lrn(in_layer,
                                depth_radius=np.float(depth_radius),
                                bias=np.float(bias),
                                alpha=alpha,
                                beta=beta,
                                name='norm')
        self.params = {'input': in_layer.name,
                       'type': 'lrnorm',
                       'depth_radius': depth_radius,
                       'bias': bias,
                       'alpha': alpha,
                       'beta': beta}
        return self.output

    @tf.contrib.framework.add_arg_scope
    def pool(self,
             ksize=3,
             stride=2,
             padding='SAME',
             in_layer=None):
        if in_layer is None: in_layer = self.output

        if isinstance(ksize, int):
            ksize1 = ksize
            ksize2 = ksize
        else:
            ksize1, ksize2 = ksize

        self.output = tf.nn.max_pool(in_layer,
                                     ksize=[1, ksize1, ksize2, 1],
                                     strides=[1, stride, stride, 1],
                                     padding=padding,
                                     name='pool')
        self.params = {'input': in_layer.name,
                       'type': 'maxpool',
                       'kernel_size': (ksize1, ksize2),
                       'stride': stride,
                       'padding': padding}
        return self.output

    def activation(self, kind='relu', in_layer=None):
        if in_layer is None: in_layer = self.output
        if kind == 'relu':
            out = tf.nn.relu(in_layer, name='relu')
        else:
            raise ValueError("Activation '{}' not defined".format(kind))
        self.output = out
        return out

    def dropout(self, dropout=.5, in_layer=None):
        if in_layer is None: in_layer = self.output
        self.output = tf.nn.dropout(in_layer, dropout, seed=self.seed, name='dropout')
        return self.output


def mnist(inputs, train=True, **kwargs):
    m = ConvNet(**kwargs)
    reuse = None if train else True

    with tf.contrib.framework.arg_scope([m.fc], init='trunc_norm', stddev=.01,
                                        bias=0, activation='relu', dropout=None):
        with tf.variable_scope('hidden1', reuse=reuse):
            m.fc(128, in_layer=inputs)

        with tf.variable_scope('hidden2', reuse=reuse):
            m.fc(32)

        with tf.variable_scope('softmax_linear', reuse=reuse):
            m.fc(10, activation=None)

    return m


def alexnet(inputs, train=True, **kwargs):
    m = ConvNet(**kwargs)
    reuse = None if train else True

    with tf.contrib.framework.arg_scope([m.conv], init='xavier',
                                        stddev=.01, bias=.1, activation='relu'):
        with tf.variable_scope('conv1', reuse=reuse):
            m.conv(96, 11, 4, padding='VALID', in_layer=inputs)
            m.norm(depth_radius=5, bias=1, alpha=.0001, beta=.75)
            m.pool(3, 2)

        with tf.variable_scope('conv2', reuse=reuse):
            m.conv(256, 5, 1)
            m.norm(depth_radius=5, bias=1, alpha=.0001, beta=.75)
            m.pool(3, 2)

        with tf.variable_scope('conv3', reuse=reuse):
            m.conv(384, 3, 1)

        with tf.variable_scope('conv4', reuse=reuse):
            m.conv(256, 3, 1)

        with tf.variable_scope('conv5', reuse=reuse):
            m.conv(256, 3, 1)
            m.pool(3, 2)

        with tf.variable_scope('fc6', reuse=reuse):
            m.fc(4096, init='trunc_norm', dropout=.5)

        with tf.variable_scope('fc7', reuse=reuse):
            m.fc(4096, init='trunc_norm', dropout=.5)

        with tf.variable_scope('fc8', reuse=reuse):
            m.fc(1000, init='trunc_norm', activation=None, dropout=None)

    return m


def alexnet_nonorm(inputs, train=True, **kwargs):
    m = ConvNet(**kwargs)
    reuse = None if train else True

    with tf.contrib.framework.arg_scope([m.conv], init='xavier',
                                        stddev=.01, bias=.1, activation='relu'):
        with tf.variable_scope('conv1', reuse=reuse):
            m.conv(96, 11, 4, padding='VALID', in_layer=inputs)
            m.pool(3, 2)

        with tf.variable_scope('conv2', reuse=reuse):
            m.conv(256, 5, 1)
            m.pool(3, 2)

        with tf.variable_scope('conv3', reuse=reuse):
            m.conv(384, 3, 1)

        with tf.variable_scope('conv4', reuse=reuse):
            m.conv(256, 3, 1)

        with tf.variable_scope('conv5', reuse=reuse):
            m.conv(256, 3, 1)
            m.pool(3, 2)

        with tf.variable_scope('fc6', reuse=reuse):
            m.fc(4096, init='trunc_norm', dropout=.5)

        with tf.variable_scope('fc7', reuse=reuse):
            m.fc(4096, init='trunc_norm', dropout=.5)

        with tf.variable_scope('fc8', reuse=reuse):
            m.fc(1000, init='trunc_norm', activation=None, dropout=None)

    return m


def mnist_tfutils(inputs, train=True, **kwargs):
    m = mnist(inputs['images'], train=train, **kwargs)
    return m.output, m.params


def alexnet_tfutils(inputs, train=True, **kwargs):
    m = alexnet(inputs['images'], train=train, **kwargs)
    return m.output, m.params