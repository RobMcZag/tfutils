from __future__ import absolute_import, division, print_function

import os, sys, time, math

import numpy as np
import pymongo
import tensorflow as tf
from tensorflow.contrib.learn import NanLossDuringTrainingError
import gridfs


class Saver(tf.train.Saver):

    def __init__(self,
                 sess,
                 host='localhost',
                 port=31001,
                 dbname=None,
                 collname='test',
                 exp_id=None,
                 restore_vars=False,
                 restore_var_file='',
                 save_filters_to_db=False,
                 start_step=None,
                 save_vars=True,
                 save_vars_freq=3000,
                 save_path='',
                 save_loss=True,
                 save_loss_freq=5,
                 tensorboard=False,
                 tensorboard_dir='',
                 *args, **kwargs):
        """
        Output printer, logger and saver to a database

        NOTE: Not working yet
        """
        super(Saver, self).__init__(*args, **kwargs)
        if dbname is not None:
            self.conn = pymongo.MongoClient(host=host, port=port)
            self.coll = self.conn[dbname][collname + '.files']
            self.collfs = gridfs.GridFS(self.conn[dbname], collname)
            self.collfs_recent = gridfs.GridFS(self.conn[dbname + '__RECENT'],collname)
            self.save_filters_to_db = save_filters_to_db
        else:
            # TODO: save locally
            raise ValueError('Please specify database name for storing data')
        self.sess = sess
        self.exp_id = exp_id
        self.save_vars = save_vars
        self.save_vars_freq = save_vars_freq
        self.save_path = save_path
        self.save_loss = save_loss
        self.save_loss_freq = save_loss_freq
        if restore_vars:
            self.restore_model(restore_var_file)
            print('Variables restored')

        if tensorboard:  # save graph to tensorboard
            tf.train.SummaryWriter(tensorboard_dir, tf.get_default_graph())

        self.start_time_step = time.time()  # start timer

    def restore_model(self):
        """
        Fetches record, saves locally, then uses tf's saver.restore
        """
        # fetch record from database and get the filename info from record
        rec = self.load_from_db(self.exp_id)
        # should be of form *-1000 (step)
        filename_suffix = rec.filename.split('/')[-1]
        loaded_filename = os.path.join(self.save_path, 'retrieved_' + filename_suffix)

        # create new file to write from gridfs
        load_dest = open(loaded_filename, "w+")
        load_dest.close()
        load_dest = open(loaded_filename, 'rwb+')
        fsbucket = gridfs.GridFSBucket(rec._GridOut__files.database,
                            bucket_name=rec._GridOut__files.name.split('.')[0])
        # save to local disk
        fsbucket.download_to_stream(rec._id, load_dest)

        # tf restore
        self.restore(self.sess, loaded_filename)
        print('Model variables restored.')

    def load_from_db(self, query):
        """
        Loads checkpoint from the database

        Checks the recent and regular checkpoint fs to find the latest one
        matching the query. Returns the GridOut obj corresponding to the
        record.

        Args:
            query: dict of Mongo queries
        """
        count = self.collfs.find(query).count()
        if count > 0:  # get latest that matches query
            ckpt_record = self.collfs._GridFS__files.find(query,
                            sort=[('uploadDate', -1)])[0]
            loading_from = 'long-term storage'

        count_recent = self.collfs_recents.find(query).count()
        if count_recent > 0:  # get latest that matches query
            ckpt_record_rec = self.collfs_recent._GridFS__files.find(query,
                                sort=[('uploadDate', -1)])[0]
            # use the record with latest timestamp
            if ckpt_record is None or ckpt_record_rec['uploadDate'] > ckpt_record['uploadDate']:
                loading_from = 'recent storage'
                ckpt_record = ckpt_record_rec

        if count + count_recent == 0:  # no matches for query
            raise Exception('No matching checkpoint for query "{}"'.format(repr(query)))

        print('Loading checkpoint from ', loading_from)
        return ckpt_record

    def save(self, step, results):
        elapsed_time_step = time.time() - self.start_time_step
        self.start_time_step = time.time()

        if math.isnan(results['loss']):
            raise NanLossDuringTrainingError

        rec = {'exp_id': self.exp_id,
            #    'cfg': preprocess_config(cfg),
            #    'saved_filters': saved_filters,
                'kind': 'train',
                'step': step,
                'loss': float(results['loss']),
                'learning_rate': float(results['lr']),
                'duration': int(1000 * elapsed_time_step)}

        if step > 0:
            # write loss to db
            if self.save_loss and step % self.save_loss_freq == 0:
                self.coll.insert_one(rec)


        if self.save_vars and step % self.save_vars_freq == 0 and step > 0:
            saved_path = super(Saver, self).save(self.sess,
                                    save_path=self.save_path,
                                    global_step=step,
                                    write_meta_graph=False)
            # save the saved file to 'recent' checkpoint fs
            if self.save_filters_to_db:
                self.collfs_recent.put(open(saved_path, 'rb'),
                                       filename=saved_path,
                                       saved_filters=True,
                                       **rec)
                # TODO: when do we move from recent to non recent...
                print('Saved variable checkpoint to recent fs.')

        print('Step {} -- loss: {:.6f}, lr: {:.6f}, time: {:.0f}'
              'ms'.format(rec['step'], rec['loss'], rec['learning_rate'], rec['duration']))
        sys.stdout.flush()  # flush the stdout buffer

    def valid(self, step, results):
        elapsed_time_step = time.time() - self.start_time_step
        self.start_time_step = time.time()
        rec = {'exp_id': self.exp_id,
            #    'cfg': preprocess_config(cfg),
            #    'saved_filters': saved_filters,
               'kind': 'validation',
               'step': step,
               'duration': 1000 * elapsed_time_step}
        rec.update(results)
        if step > 0:
            # write loss to file
            if self.save_valid and step % self.save_valid_freq == 0:
                pass
                # self.coll.insert(rec)

        message = ('Step {} validation -- ' +
                   '{}: {:.3f}, ' * len(results) +
                   '{:.0f} ms')
        args = []
        for k, v in results.items():
            args.extend([k,v])
        args = [rec['step']] + args + [rec['duration']]
        print(message.format(*args))

    def predict(self, step, results):
        if not hasattr(results['output'], '__iter__'):
            outputs = [results['outputs']]
        else:
            outputs = results['outputs']

        preds = [tf.argmax(output, 1) for output in outputs]

        return preds

    def test(self, step, results):
        raise NotImplementedError



def run_loop(sess, queues, saver, train_targets, valid_targets=None,
        start_step=0, end_step=None):
    """
    Args:
        - queues (~ data)
        - saver
        - targets
    """
    # initialize and/or restore variables for graph
    init = tf.initialize_all_variables()
    sess.run(init)
    print('variables initialized')

    tf.train.start_queue_runners(sess=sess)
    # start our custom queue runner's threads
    if not hasattr(queues, '__iter__'):
        queues = [queues]
    for queue in queues:
        queue.start_threads(sess)

    # start_time_step = time.time()  # start timer
    print('start training')
    for step in xrange(start_step, end_step):
        # get run output as dictionary {'2': loss2, 'lr': lr, etc..}
        results = sess.run(train_targets)
        # print output, save variables to checkpoint and save loss etc
        saver.save(step, results)
    sess.close()


def run(model_func,
        model_func_kwargs,
        data_func,
        data_func_kwargs,
        loss_func,
        loss_func_kwargs,
        lr_func,
        lr_func_kwargs,
        opt_func,
        opt_func_kwargs,
        saver_kwargs,
        train_targets=None,
        valid_targets=None,
        seed=None,
        start_step=0,
        end_step=float('inf'),
        log_device_placement=True
        ):
    with tf.Graph().as_default():  # to have multiple graphs [ex: eval, train]
        rng = np.random.RandomState(seed=seed)
        tf.set_random_seed(seed)

        tf.get_variable('global_step', [],
                        initializer=tf.constant_initializer(0),
                        trainable=False)

        train_data_node, train_labels_node, train_data_provider = data_func(train=True, **data_func_kwargs)
        valid_data_node, valid_labels_node, valid_data_provider = data_func(train=False, **data_func_kwargs)

        train_outputs = model_func(train_data_node, train=True, **model_func_kwargs)
        loss = loss_func(train_outputs, train_labels_node, **loss_func_kwargs)
        lr = lr_func(**lr_func_kwargs)
        optimizer = opt_func(loss, lr, **opt_func_kwargs)

        ttarg = {'loss': loss, 'lr': lr, 'opt': optimizer}
        if train_targets is None:
            train_targets = ttarg
        elif isinstance(train_targets, dict):
            train_targets.update(ttarg)
        else:
            raise ValueError('Train targets must be None or dict, got {}'.format(type(train_targets)))

        valid_outputs = model_func(valid_data_node, train=False, **model_func_kwargs)
        top_1_ops = [tf.nn.in_top_k(output, labels, 1)
                    for output, labels in zip(valid_outputs, valid_labels_node)]
        top_5_ops = [tf.nn.in_top_k(output, labels, 5)
                    for output, labels in zip(valid_outputs, valid_labels_node)]
        vtarg = {'top1': top_1_ops, 'top5': top_5_ops}
        if valid_targets is None:
            valid_targets = vtarg
        elif isinstance(valid_targets, dict):
            valid_targets.update(vtarg)
        else:
            raise ValueError('Validation targets must be None or dict, got {}'.format(type(valid_targets)))

        # create session
        sess = tf.Session(config=tf.ConfigProto(
                                allow_soft_placement=True,
                                log_device_placement=log_device_placement))

        saver = Saver(sess, **saver_kwargs)
        run_loop(sess,
            [train_data_provider, valid_data_provider],
            saver,
            train_targets=train_targets,
            valid_targets=valid_targets,
            start_step=start_step,
            end_step=end_step)
