"""
These tests show basic procedures for training, validating, and extracting features from
models.

Note about MongoDB:
The tests require a MongoDB instance to be available on the port defined by "testport" in
the code below.   This db can either be local to where you run these tests (and therefore
on 'localhost' by default) or it can be running somewhere else and then by ssh-tunneled on
the relevant port to the host where you run these tests.  [That is, before testing, you'd run
         ssh -f -N -L  [testport]:localhost:[testport] [username]@mongohost.xx.xx
on the machine where you're running these tests.   [mongohost] is the where the mongodb
instance is running.
"""
from __future__ import division, print_function, absolute_import

import os
import sys
import cPickle
from collections import OrderedDict

import gridfs
import numpy as np
import pymongo as pm
import tensorflow as tf

sys.path.append("/home/aandonia/tfutils")
from tfutils import base, model, utils, data, optimizer


num_batches_per_epoch = 10000 // 256

testhost = 'localhost'       # Host on which the MongoDB instance to be used by tests needs to be running
testport = int(os.environ.get('TFUTILS_TEST_DBPORT', 27017))  # port on which the MongoDB instance to be used by tests needs to be running
testdbname = 'tfutils-test'  # name of the mongodb database where results will be stored by tests
testcol = 'testcol'          # name of the mongodb collection where results will be stored by tests


def test_training():
    """This test illustrates how basic training is performed using the
       tfutils.base.train_from_params function.  This is the first in a sequence of
       interconnected tests. It creates a pretrained model that is used by
       the next few tests (test_validation and test_feature_extraction).

       As can be seen by looking at how the test checks for correctness, after the
       training is run, results of training, including (intermittently) the full variables
       needed to re-initialize the tensorflow model, are stored in a MongoDB.

       Also see docstring of the tfutils.base.train_from_params function for more detailed
       information about usage.
    """
    # delete old database if it exists
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    conn.drop_database(testdbname)
    nm = testdbname + '_' + testcol + '_training0'
    [conn.drop_database(x) for x in conn.database_names() if x.startswith(nm) and '___RECENT' in x]
    nm = testdbname + '_' + testcol + '_training1'
    [conn.drop_database(x) for x in conn.database_names() if x.startswith(nm) and '___RECENT' in x]

    # set up the parameters
    params = {}
    #  everything is list except 'train_params'
    params['model_params'] = {'func': model.mnist_tfutils}
    params['save_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0',
                             'save_valid_freq': 20,
                             'save_filters_freq': 200,
                             'cache_filters_freq': 100,
                             }
    params['train_params'] = {'data_params': {'func': data.MNIST,
                                              'batch_size': 100,
                                              'group': 'train',
                                              'n_threads': 4},
                              'queue_params': {'queue_type': 'fifo',
                                               'batch_size': 100},
                              'num_steps': 500
                              }
    params['learning_rate_params'] = {'learning_rate': 0.05,
                                      'decay_steps': num_batches_per_epoch,
                                      'decay_rate': 0.95,
                                      'staircase': True}
    params['validation_params'] = {'valid0': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'num_steps': 10,
                                              'agg_func': utils.mean_dict}}

    test_params = generate_test_params({'func': model.mnist_tfutils})

    assert params == test_params

    # actually run the training
    base.train_from_params(**params)
    # test if results are as expected

    DEBUG = OrderedDict()
    DEBUG['count0'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count()
    DEBUG['distinct_filters0'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step')

    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 26
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step') == [0, 200, 400]

    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 0})[0]
    asserts_for_record(r, params, train=True)
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 20})[0]
    asserts_for_record(r, params, train=True)

    # run another 500 steps of training on the same experiment id.
    params['train_params']['num_steps'] = 1000
    base.train_from_params(**params)
    # test if results are as expected
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 51
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0',
                                                      'saved_filters': True}).distinct('step') == [0, 200, 400, 600, 800, 1000]
    assert conn['tfutils-test']['testcol.files'].distinct('exp_id') == ['training0']

    DEBUG['count1'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count()
    DEBUG['distinct_filters1'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step')
    DEBUG['distinct_exp_id'] = conn['tfutils-test']['testcol.files'].distinct('exp_id')

    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 1000})[0]

    asserts_for_record(r, params, train=True)

    # run 500 more steps but save to a new experiment id.
    params['train_params']['num_steps'] = 1500
    params['load_params'] = {'exp_id': 'training0'}
    params['save_params']['exp_id'] = 'training1'
    base.train_from_params(**params)
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training1',
                                                      'saved_filters': True}).distinct('step') == [1200, 1400]
    DEBUG['distinct_filters2'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training1', 'saved_filters': True}).distinct('step')
    print(DEBUG)

    return DEBUG


def test_parallel_training():
    """This test illustrates how basic parallel training is performed using the
       tfutils.base.train_from_params function.  This runs identically to the test
       above, although now models are distributed over multiple GPUs in a node.

    """
    testcol = 'testcol_parallel'
    conn = pm.MongoClient(host=testhost,
                          port=testport)

    conn.drop_database(testdbname)
    nm = testdbname + '_' + testcol + '_training0'
    [conn.drop_database(x) for x in conn.database_names() if x.startswith(nm) and '___RECENT' in x]
    nm = testdbname + '_' + testcol + '_training1'
    [conn.drop_database(x) for x in conn.database_names() if x.startswith(nm) and '___RECENT' in x]

    # set up the parameters
    params = {}

    model1_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:0', '/gpu:1']}
    model2_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:2', '/gpu:3']}

    save1_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol,
                    'exp_id': 'training0',
                    'save_valid_freq': 20,
                    'save_filters_freq': 200,
                    'cache_filters_freq': 100,
                    'model_prefix': 'MODEL_1'}

    save2_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol,
                    'exp_id': 'training0',
                    'save_valid_freq': 20,
                    'save_filters_freq': 200,
                    'cache_filters_freq': 100,
                    'model_prefix': 'MODEL_2'}

    train_params = {'data_params': {'func': data.MNIST,
                                    'batch_size': 10,
                                    'group': 'train',
                                    'n_threads': 4},
                    'queue_params': {'queue_type': 'fifo',
                                     'batch_size': 10},
                    'num_steps': 500}

    loss_params = {'targets': ['labels'],
                   'agg_func': tf.reduce_mean,
                   'loss_per_case_func': tf.nn.sparse_softmax_cross_entropy_with_logits}

    learning_rate_params = {'learning_rate': 0.05,
                            'decay_steps': num_batches_per_epoch,
                            'decay_rate': 0.95,
                            'staircase': True}

    validation_params = {'valid0': {'data_params': {'func': data.MNIST,
                                                    'batch_size': 10,
                                                    'group': 'test',
                                                    'n_threads': 4},
                                    'queue_params': {'queue_type': 'fifo',
                                                     'batch_size': 10},
                                    'num_steps': 10,
                                    'agg_func': utils.mean_dict}}
    optimizer_params = {'func': optimizer.ClipOptimizer,
                        'optimizer_class': tf.train.MomentumOptimizer,
                        'clip': True,
                        'momentum': 0.9}

    load_params = {'do_restore': True}

    params['model_params'] = [model1_params, model2_params]
    params['save_params'] = [save1_params, save2_params]

    num_models = len(params['model_params'])

    params['train_params'] = train_params
    params['load_params'] = num_models * [load_params]
    params['loss_params'] = num_models * [loss_params]
    params['optimizer_params'] = num_models * [optimizer_params]
    params['validation_params'] = num_models * [validation_params]
    params['learning_rate_params'] = num_models * [learning_rate_params]

    DEBUG = OrderedDict()
    # actually run the training
    base.train_from_params(**params)

    # test if results are as expected
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 26 * num_models
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step') == [0, 200, 400]

    DEBUG['count0'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count()
    DEBUG['distinct_filters0'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step')

    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 0})[0]
    asserts_for_record(r, params, train=True)
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 20})[0]
    asserts_for_record(r, params, train=True)

    # run another 500 steps of training on the same experiment id.
    params['train_params']['num_steps'] = 1000
    base.train_from_params(**params)

    # test if results are as expected
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 51 * num_models
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0',
                                                      'saved_filters': True}).distinct('step') == [0, 200, 400, 600, 800, 1000]
    assert conn[testdbname][testcol + '.files'].distinct('exp_id') == ['training0']

    DEBUG['count1'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count()
    DEBUG['distinct_filters1'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step')
    DEBUG['distinct_exp_id'] = conn[testdbname][testcol + '.files'].distinct('exp_id')

    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 1000})[0]
    asserts_for_record(r, params, train=True)

    # run 500 more steps but save to a new experiment id.
    params['train_params']['num_steps'] = 1500
    params['load_params'] = {'exp_id': 'training0'}
    [p.update({'exp_id': 'training1'}) for p in params['save_params']]

    base.train_from_params(**params)

    DEBUG['distinct_filters2'] = conn[testdbname][testcol + '.files'].find({'exp_id': 'training1', 'saved_filters': True}).distinct('step')
    print(DEBUG)
    return DEBUG
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training1',
                                                      'saved_filters': True}).distinct('step') == [1200, 1400]


def custom_train_loop(sess, train_targets, **loop_params):
    print('TESTING CUSTOM TRAINING LOOP ...')
    for i, train_target in enumerate(train_targets):
        loss = sess.run(train_target['loss'])
        print('Model {} has loss {}'.format(i, loss))
    return sess.run(train_targets)


def test_custom_training():
    """This test illustrates how basic training is performed using the
       tfutils.base.train_from_params function.  This is the first in a sequence of
       interconnected tests. It creates a pretrained model that is used by
       the next few tests (test_validation and test_feature_extraction).

       As can be seen by looking at how the test checks for correctness, after the
       training is run, results of training, including (intermittently) the full variables
       needed to re-initialize the tensorflow model, are stored in a MongoDB.

       Also see docstring of the tfutils.base.train_from_params function for more detailed
       information about usage.
    """

    testcol = 'testcol_custom'
    conn = pm.MongoClient(host=testhost,
                          port=testport)

    # delete old collection if it exists
    coll = conn[testdbname][testcol + '.files']
    coll.drop()

    # set up the parameters
    params = {}
    #  everything is list except 'train_params'
    params['model_params'] = {'func': model.mnist_tfutils}
    params['save_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0',
                             'save_valid_freq': 20,
                             'save_filters_freq': 200,
                             'cache_filters_freq': 100,
                             }
    params['train_params'] = {'data_params': {'func': data.MNIST,
                                              'batch_size': 100,
                                              'group': 'train',
                                              'n_threads': 4},
                              'train_loop': {'func': custom_train_loop},
                              'queue_params': {'queue_type': 'fifo',
                                               'batch_size': 100},
                              'num_steps': 500
                              }
    params['learning_rate_params'] = {'learning_rate': 0.05,
                                      'decay_steps': num_batches_per_epoch,
                                      'decay_rate': 0.95,
                                      'staircase': True}
    params['validation_params'] = {'valid0': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'num_steps': 10,
                                              'agg_func': utils.mean_dict}}

    # actually run the training
    base.train_from_params(**params)
    # test if results are as expected
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 26
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'saved_filters': True}).distinct('step') == [0, 200, 400]

    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 0})[0]
    asserts_for_record(r, params, train=True)
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 20})[0]
    asserts_for_record(r, params, train=True)

    # run another 500 steps of training on the same experiment id.
    params['train_params']['num_steps'] = 1000
    base.train_from_params(**params)
    # test if results are as expected
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'}).count() == 51
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training0',
                                                      'saved_filters': True}).distinct('step') == [0, 200, 400, 600, 800, 1000]
    assert conn['tfutils-test']['testcol.files'].distinct('exp_id') == ['training0']
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0', 'step': 1000})[0]
    asserts_for_record(r, params, train=True)

    # run 500 more steps but save to a new experiment id.
    params['train_params']['num_steps'] = 1500
    params['load_params'] = {'exp_id': 'training0'}
    params['save_params']['exp_id'] = 'training1'
    base.train_from_params(**params)
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'training1',
                                                      'saved_filters': True}).distinct('step') == [1200, 1400]


def test_custom_parallel_training():
    """This test illustrates how basic parallel training is performed using the
       tfutils.base.train_from_params function.  This runs identically to the test
       above, although now models are distributed over multiple GPUs in a node.

    """
    testcol = 'testcol_custom_parallel'
    conn = pm.MongoClient(host=testhost,
                          port=testport)

    # delete old collection if it exists
    coll = conn[testdbname][testcol + '.files']
    coll.drop()

    # set up the parameters
    params = {}
    #  everything is list except 'train_params'
    model1_params = {'func': model.mnist_tfutils,
                     'devices': [0, 1]}
    model2_params = {'func': model.mnist_tfutils,
                     'devices': [2, 3]}

    save1_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol,
                    'exp_id': 'training0',
                    'save_valid_freq': 20,
                    'save_filters_freq': 200,
                    'cache_filters_freq': 100,
                    'model_prefix': 'MODEL_1'}

    save2_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol,
                    'exp_id': 'training0',
                    'save_valid_freq': 20,
                    'save_filters_freq': 200,
                    'cache_filters_freq': 100,
                    'model_prefix': 'MODEL_2'}

    train_params = {'data_params': {'func': data.MNIST,
                                    'batch_size': 100,
                                    'group': 'train',
                                    'n_threads': 4},
                    'train_loop': {'func': custom_train_loop},
                    'queue_params': {'queue_type': 'fifo',
                                     'batch_size': 100},
                    'num_steps': 500}

    loss_params = {'targets': ['labels'],
                   'agg_func': tf.reduce_mean,
                   'loss_per_case_func': tf.nn.sparse_softmax_cross_entropy_with_logits}

    learning_rate_params = {'learning_rate': 0.05,
                            'decay_steps': num_batches_per_epoch,
                            'decay_rate': 0.95,
                            'staircase': True}

    validation_params = {'valid0': {'data_params': {'func': data.MNIST,
                                                    'batch_size': 100,
                                                    'group': 'test',
                                                    'n_threads': 4},
                                    'queue_params': {'queue_type': 'fifo',
                                                     'batch_size': 100},
                                    'num_steps': 10,
                                    'agg_func': utils.mean_dict}}
    optimizer_params = {'func': optimizer.ClipOptimizer,
                        'optimizer_class': tf.train.MomentumOptimizer,
                        'clip': True,
                        'momentum': 0.9}

    load_params = {'do_restore': False,
                   'query': None}

    params['model_params'] = [model1_params, model2_params]
    params['save_params'] = [save1_params, save2_params]

    num_models = len(params['model_params'])

    params['train_params'] = train_params
    params['load_params'] = num_models * [load_params]
    params['loss_params'] = num_models * [loss_params]
    params['optimizer_params'] = num_models * [optimizer_params]
    params['validation_params'] = num_models * [validation_params]
    params['learning_rate_params'] = num_models * [learning_rate_params]

    for key, value in params.items():
        if key == 'train_params':
            assert(isinstance(value, dict))
        else:
            assert len(value) == num_models

    base.train_from_params(**params)


def get_first_image_target(inputs, outputs, **ttarg_params):
    """A target for saving the first image of every batch.
      Used in test_training test below to test save_to_gfs option.
    """
    return {'first_image': inputs['images'][0]}


def test_training_save():
    """This test illustrates saving to the grid file system during training time.
    """
    exp_id = 'training2'
    testcol_2 = 'testcol2'
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    # delete old collection if it exists
    coll = conn[testdbname][testcol_2 + '.files']
    coll.drop()

    # set up the parameters
    params = {}

    params['model_params'] = {'func': model.mnist_tfutils}

    params['save_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol_2,
                             'exp_id': exp_id,
                             'save_valid_freq': 3000,
                             'save_filters_freq': 30000,
                             'cache_filters_freq': 3000,
                             'save_to_gfs': ['first_image']}

    params['train_params'] = {'data_params': {'func': data.MNIST,
                                              'batch_size': 100,
                                              'group': 'train',
                                              'n_threads': 4},
                              'queue_params': {'queue_type': 'fifo',
                                               'batch_size': 100},
                              'num_steps': 500,
                              'targets': {'func': get_first_image_target}}

    params['learning_rate_params'] = {'learning_rate': 0.05,
                                      'decay_steps': num_batches_per_epoch,
                                      'decay_rate': 0.95,
                                      'staircase': True}

    # actually run the training
    base.train_from_params(**params)

    # check that the first image has been saved
    q = {'exp_id': exp_id, 'train_results': {'$exists': True}}
    coll = conn[testdbname][testcol_2 + '.files']
    train_steps = coll.find(q)
    assert train_steps.count() == 5, (train_steps.count(), 5)
    idx = train_steps[0]['_id']
    fn = coll.find({'item_for': idx})[0]['filename']
    fs = gridfs.GridFS(coll.database, testcol_2)
    fh = fs.get_last_version(fn)
    saved_data = cPickle.loads(fh.read())
    fh.close()
    assert 'train_results' in saved_data and 'first_image' in saved_data['train_results']
    assert len(saved_data['train_results']['first_image']) == 100, (len(saved_data['train_results']['first_image']), 100)
    assert saved_data['train_results']['first_image'][0].shape == (28 * 28,), (saved_data['train_results']['first_image'][0].shape, (28 * 28,))


def test_parallel_training_save():
    """This test illustrates saving to the grid file system during training time.
    """
    exp_id = 'training2'
    testcol_2 = 'testcol2_parallel'
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    # delete old collection if it exists
    coll = conn[testdbname][testcol_2 + '.files']
    coll.drop()

    # set up the parameters
    params = {}

    model1_params = {'func': model.mnist_tfutils,
                     'devices': [0, 1]}
    model2_params = {'func': model.mnist_tfutils,
                     'devices': [2, 3]}

    save1_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol_2,
                    'exp_id': exp_id,
                    'save_valid_freq': 3000,
                    'save_filters_freq': 30000,
                    'cache_filters_freq': 3000,
                    'save_to_gfs': ['first_image'],
                    # 'model_prefix': 'MODEL_1',
                    }

    save2_params = {'host': testhost,
                    'port': testport,
                    'dbname': testdbname,
                    'collname': testcol_2,
                    'exp_id': exp_id,
                    'save_valid_freq': 3000,
                    'save_filters_freq': 30000,
                    'cache_filters_freq': 3000,
                    'save_to_gfs': ['first_image'],
                    # 'model_prefix': 'MODEL_2',
                    }

    params['model_params'] = [model1_params, model2_params]

    params['save_params'] = [save1_params, save2_params]

    params['train_params'] = {'data_params': {'func': data.MNIST,
                                              'batch_size': 100,
                                              'group': 'train',
                                              'n_threads': 4},
                              'queue_params': {'queue_type': 'fifo',
                                               'batch_size': 100},
                              'num_steps': 500,
                              'targets': {'func': get_first_image_target}}

    params['learning_rate_params'] = {'learning_rate': 0.05,
                                      'decay_steps': num_batches_per_epoch,
                                      'decay_rate': 0.95,
                                      'staircase': True}

    # actually run the training
    base.train_from_params(**params)

    # check that the first image has been saved
    q = {'exp_id': exp_id, 'train_results': {'$exists': True}}
    coll = conn[testdbname][testcol_2 + '.files']
    train_steps = coll.find(q)
    assert train_steps.count() == 10, (train_steps.count(), 10)
    idx = train_steps[0]['_id']
    fn = coll.find({'item_for': idx})[0]['filename']
    fs = gridfs.GridFS(coll.database, testcol_2)
    fh = fs.get_last_version(fn)
    saved_data = cPickle.loads(fh.read())
    fh.close()
    assert 'train_results' in saved_data and 'first_image' in saved_data['train_results']
    assert len(saved_data['train_results']['first_image']) == 100, (len(saved_data['train_results']['first_image']), 100)
    assert saved_data['train_results']['first_image'][0].shape == (28 * 28,), (saved_data['train_results']['first_image'][0].shape, (28 * 28,))


def test_validation():
    """
    This is a test illustrating how to compute performance on a trained model on a new dataset,
    using the tfutils.base.test_from_params function.  This test assumes that test_training function
    has run first (to provide a pre-trained model to validate).

    After the test is run, results from the validation are stored in the MongoDB.
    (The test shows how the record can be loaded for inspection.)

    See the docstring of tfutils.base.test_from_params for more detailed information on usage.
    """

    # delete old validation document if it exists
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    coll = conn[testdbname][testcol + '.files']
    coll.delete_many({'exp_id': 'validation0'})

    # specify the parameters for the validation
    params = {}

    params['model_params'] = {'func': model.mnist_tfutils}

    params['load_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0'}

    params['save_params'] = {'exp_id': 'validation0'}

    params['validation_params'] = {'valid0': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'num_steps': 10,
                                              'agg_func': utils.mean_dict}}

    # actually run the model
    base.test_from_params(**params)

    # check that the results are correct
    conn = pm.MongoClient(host=testhost,
                          port=testport)

    # ... specifically, there is now a record containing the validation0 performance results
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'}).count() == 1
    # ... here's how to load the record:
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'})[0]
    asserts_for_record(r, params, train=False)

    # ... check that the recorrectly ties to the id information for the
    # pre-trained model it was supposed to validate
    assert r['validates']
    idval = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'})[50]['_id']
    v = conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'})[0]['validates']
    assert idval == v


def test_parallel_validation():
    """
    This is a test illustrating how to compute performance on a trained model on a new dataset,
    using the tfutils.base.test_from_params function.  This test assumes that test_training function
    has run first (to provide a pre-trained model to validate).

    After the test is run, results from the validation are stored in the MongoDB.
    (The test shows how the record can be loaded for inspection.)

    See the docstring of tfutils.base.test_from_params for more detailed information on usage.
    """

    # delete old validation document if it exists
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    coll = conn[testdbname][testcol + '.files']
    coll.delete_many({'exp_id': 'validation0'})

    # specify the parameters for the validation
    params = {}

    model1_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:0', '/gpu:1']}
    model2_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:2', '/gpu:3']}

    params['model_params'] = [model1_params, model2_params]

    params['load_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0'}

    params['save_params'] = {'exp_id': 'validation0'}

    params['validation_params'] = {'valid0': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'num_steps': 10,
                                              'agg_func': utils.mean_dict}}

    # actually run the model
    base.test_from_params(**params)

    # check that the results are correct
    conn = pm.MongoClient(host=testhost,
                          port=testport)

    # ... specifically, there is now a record containing the validation0 performance results
    assert conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'}).count() == 1
    # ... here's how to load the record:
    r = conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'})[0]
    asserts_for_record(r, params, train=False)

    # ... check that the recorrectly ties to the id information for the
    # pre-trained model it was supposed to validate
    assert r['validates']
    idval = conn[testdbname][testcol + '.files'].find({'exp_id': 'training0'})[50]['_id']
    v = conn[testdbname][testcol + '.files'].find({'exp_id': 'validation0'})[0]['validates']
    assert idval == v


def get_extraction_target(inputs, outputs, to_extract, **loss_params):
    """
    Example validation target function to use to provide targets for extracting features.
    This function also adds a standard "loss" target which you may or not may not want

    The to_extract argument must be a dictionary of the form
          {name_for_saving: name_of_actual_tensor, ...}
    where the "name_for_saving" is a human-friendly name you want to save extracted
    features under, and name_of_actual_tensor is a name of the tensor in the tensorflow
    graph outputing the features desired to be extracted.  To figure out what the names
    of the tensors you want to extract are "to_extract" argument,  uncomment the
    commented-out lines, which will print a list of all available tensor names.
    """

    # names = [[x.name for x in op.values()] for op in tf.get_default_graph().get_operations()]
    # print("NAMES are: ", names)

    targets = {k: tf.get_default_graph().get_tensor_by_name(v) for k, v in to_extract.items()}
    targets['loss'] = utils.get_loss(inputs, outputs, **loss_params)
    return targets


def test_feature_extraction():
    """
    This is a test illustrating how to perform feature extraction using
    tfutils.base.test_from_params.
    The basic idea is to specify a validation target that is simply the actual output of
    the model at some layer. (See the "get_extraction_target" function above as well.)
    This test assumes that test_train has run first.

    After the test is run, the results of the feature extraction are saved in the Grid
    File System associated with the mongo database, with one file per batch of feature
    results.  See how the features are accessed by reading the test code below.
    """
    # set up parameters
    exp_id = 'validation1'

    params = {}

    params['model_params'] = {'func': model.mnist_tfutils}

    params['load_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0'}

    params['save_params'] = {'exp_id': exp_id,
                             'save_intermediate_freq': 1,
                             'save_to_gfs': ['features', 'more_features']}

    targdict = {'func': get_extraction_target,
                'to_extract': {'features': 'validation/valid1/hidden1/output:0',
                               'more_features': 'validation/valid1/hidden2/output:0'}}

    targdict.update(base.DEFAULT_LOSS_PARAMS)
    params['validation_params'] = {'valid1': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'targets': targdict,
                                              'num_steps': 10,
                                              'online_agg_func': utils.reduce_mean_dict}}

    # actually run the feature extraction
    base.test_from_params(**params)

    # check that things are as expected.
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    coll = conn[testdbname][testcol + '.files']
    assert coll.find({'exp_id': exp_id}).count() == 11

    # ... load the containing the final "aggregate" result after all features have been extracted
    q = {'exp_id': exp_id, 'validation_results.valid1.intermediate_steps': {'$exists': True}}
    assert coll.find(q).count() == 1
    r = coll.find(q)[0]
    # ... check that the record is well-formed
    asserts_for_record(r, params, train=False)

    # ... check that the correct "intermediate results" (the actual features extracted) records exist
    # and are correctly referenced.
    q1 = {'exp_id': exp_id, 'validation_results.valid1.intermediate_steps': {'$exists': False}}
    ids = coll.find(q1).distinct('_id')
    assert r['validation_results']['valid1']['intermediate_steps'] == ids

    # ... actually load feature batch 3
    idval = r['validation_results']['valid1']['intermediate_steps'][3]
    fn = coll.find({'item_for': idval})[0]['filename']
    fs = gridfs.GridFS(coll.database, testcol)
    fh = fs.get_last_version(fn)
    saved_data = cPickle.loads(fh.read())
    fh.close()
    first_results = saved_data['validation_results']['valid1']
    assert 'features' in first_results and 'more_features' in first_results
    features = saved_data['validation_results']['valid1']['features']
    more_features = saved_data['validation_results']['valid1']['more_features']
    assert features.shape == (100, 128)
    assert features.dtype == np.float32
    assert more_features.shape == (100, 32)
    assert more_features.dtype == np.float32


def test_parallel_feature_extraction():
    """
    This is a test illustrating how to perform feature extraction using
    tfutils.base.test_from_params.
    The basic idea is to specify a validation target that is simply the actual output of
    the model at some layer. (See the "get_extraction_target" function above as well.)
    This test assumes that test_train has run first.

    After the test is run, the results of the feature extraction are saved in the Grid
    File System associated with the mongo database, with one file per batch of feature
    results.  See how the features are accessed by reading the test code below.
    """
    # set up parameters
    exp_id = 'validation1'

    params = {}

    model1_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:0', '/gpu:1']}
    model2_params = {'func': model.mnist_tfutils,
                     'devices': ['/gpu:2', '/gpu:3']}

    params['model_params'] = [model1_params, model2_params]

    params['load_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0'}

    params['save_params'] = {'exp_id': exp_id,
                             'save_intermediate_freq': 1,
                             'save_to_gfs': ['features', 'more_features']}

    targdict = {'func': get_extraction_target,
                'to_extract': {'features': 'validation/valid1/hidden1/output:0',
                               'more_features': 'validation/valid1/hidden2/output:0'}}

    targdict.update(base.DEFAULT_LOSS_PARAMS)
    params['validation_params'] = {'valid1': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'targets': targdict,
                                              'num_steps': 10,
                                              'online_agg_func': utils.reduce_mean_dict}}

    # actually run the feature extraction
    base.test_from_params(**params)

    # check that things are as expected.
    conn = pm.MongoClient(host=testhost,
                          port=testport)
    coll = conn[testdbname][testcol + '.files']
    assert coll.find({'exp_id': exp_id}).count() == 11

    # ... load the containing the final "aggregate" result after all features have been extracted
    q = {'exp_id': exp_id, 'validation_results.valid1.intermediate_steps': {'$exists': True}}
    assert coll.find(q).count() == 1
    r = coll.find(q)[0]
    # ... check that the record is well-formed
    asserts_for_record(r, params, train=False)

    # ... check that the correct "intermediate results" (the actual features extracted) records exist
    # and are correctly referenced.
    q1 = {'exp_id': exp_id, 'validation_results.valid1.intermediate_steps': {'$exists': False}}
    ids = coll.find(q1).distinct('_id')
    assert r['validation_results']['valid1']['intermediate_steps'] == ids

    # ... actually load feature batch 3
    idval = r['validation_results']['valid1']['intermediate_steps'][3]
    fn = coll.find({'item_for': idval})[0]['filename']
    fs = gridfs.GridFS(coll.database, testcol)
    fh = fs.get_last_version(fn)
    saved_data = cPickle.loads(fh.read())
    fh.close()
    first_results = saved_data['validation_results']['valid1']
    assert 'features' in first_results and 'more_features' in first_results
    features = saved_data['validation_results']['valid1']['features']
    more_features = saved_data['validation_results']['valid1']['more_features']
    assert features.shape == (100, 128)
    assert features.dtype == np.float32
    assert more_features.shape == (100, 32)
    assert more_features.dtype == np.float32


def asserts_for_record(r, params, train=False):
    if r.get('saved_filters'):
        assert r['_saver_write_version'] == 2
        assert r['_saver_num_data_files'] == 1
    assert type(r['duration']) == float

    should_contain = ['save_params', 'load_params', 'model_params', 'validation_params']
    assert set(should_contain).difference(r['params'].keys()) == set()

    vk = r['params']['validation_params'].keys()
    vk1 = r['validation_results'].keys()
    assert set(vk) == set(vk1)

    assert r['params']['model_params']['seed'] == 0
    assert r['params']['model_params']['func']['modname'] == 'tfutils.model'
    assert r['params']['model_params']['func']['objname'] == 'mnist_tfutils'
    assert set(['hidden1', 'hidden2', u'softmax_linear']).difference(r['params']['model_params']['cfg_final'].keys()) == set()

    _k = vk[0]
    should_contain = ['agg_func', 'data_params', 'num_steps', 'online_agg_func', 'queue_params', 'targets']
    assert set(should_contain).difference(r['params']['validation_params'][_k].keys()) == set()

    if train:
        assert r['params']['model_params']['train'] is True
        for k in ['num_steps', 'queue_params']:
            assert r['params']['train_params'][k] == params['train_params'][k]

        should_contain = ['loss_params', 'optimizer_params', 'train_params', 'learning_rate_params']
        assert set(should_contain).difference(r['params'].keys()) == set()
        assert r['params']['train_params']['thres_loss'] == 100
        assert r['params']['train_params']['data_params']['func']['modname'] == 'tfutils.data'
        assert r['params']['train_params']['data_params']['func']['objname'] == 'MNIST'

        assert r['params']['loss_params']['agg_func']['modname'] == 'tensorflow.python.ops.math_ops'
        assert r['params']['loss_params']['agg_func']['objname'] == 'reduce_mean'
        assert r['params']['loss_params']['loss_per_case_func']['modname'] == 'tensorflow.python.ops.nn_ops'
        assert r['params']['loss_params']['loss_per_case_func']['objname'] == 'sparse_softmax_cross_entropy_with_logits'
        assert r['params']['loss_params']['targets'] == ['labels']
    else:
        assert 'train' not in r['params']['model_params']
        assert 'train_params' not in r['params']


def generate_test_params(model_params,
                         custom_train_loop=None,
                         custom_valid_loop=None,
                         custom_train_targets=None,
                         custom_valid_targets=None):

    # set up the parameters
    params = {}

    params['model_params'] = model_params
    params['save_params'] = {'host': testhost,
                             'port': testport,
                             'dbname': testdbname,
                             'collname': testcol,
                             'exp_id': 'training0',
                             'save_valid_freq': 20,
                             'save_filters_freq': 200,
                             'cache_filters_freq': 100,
                             }
    params['train_params'] = {'data_params': {'func': data.MNIST,
                                              'batch_size': 100,
                                              'group': 'train',
                                              'n_threads': 4},
                              'queue_params': {'queue_type': 'fifo',
                                               'batch_size': 100},
                              'num_steps': 500
                              }
    params['learning_rate_params'] = {'learning_rate': 0.05,
                                      'decay_steps': num_batches_per_epoch,
                                      'decay_rate': 0.95,
                                      'staircase': True}
    params['validation_params'] = {'valid0': {'data_params': {'func': data.MNIST,
                                                              'batch_size': 100,
                                                              'group': 'test',
                                                              'n_threads': 4},
                                              'queue_params': {'queue_type': 'fifo',
                                                               'batch_size': 100},
                                              'num_steps': 10,
                                              'agg_func': utils.mean_dict}}
    if custom_train_loop is not None:
        params['train_params']['train_loop'] = custom_train_loop
    if custom_train_targets is not None:
        params['train_params']['targets'] = custom_train_targets
    if custom_valid_loop is not None:
        params['validation_params']['valid0']['valid_loop'] = custom_valid_loop
    if custom_valid_targets is not None:
        params['validation_params']['valid0']['targets'] = custom_valid_targets

    return params

# test_training()
# OrderedDict([('count0', 26),
#              ('distinct_filters0', [0, 200, 400]),
#              ('count1', 51),
#              ('distinct_filters1', [0, 200, 400, 600, 800, 1000]),
#              ('distinct_exp_id', [u'training0']),
#              ('distinct_filters2', [1200, 1400])])

# test_parallel_training()
# OrderedDict([('count0', 52),
#              ('distinct_filters0', [0, 200, 400]),
#              ('count1', 102),
#              ('distinct_filters1', [0, 200, 400, 600, 800, 1000]),
#              ('distinct_exp_id', [u'training0']),
#              ('distinct_filters2', [1200, 1400])])
