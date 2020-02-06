# -*- coding: utf-8 -*-
import tensorflow as tf
import cvnn.data_processing as dp
from cvnn.utils import *
from datetime import datetime
import cvnn.data_analysis as da
import matplotlib.pyplot as plt
import cvnn.activation_functions as act
from absl import logging
import cvnn.losses as loss
import numpy as np
import glob
import sys
import os
from pdb import set_trace
# https://ml-cheatsheet.readthedocs.io/en/latest/

DEBUG_RESTORE_META = False  # True to print the op and tensors that can be retrieved
DEBUG_WEIGHT_LOADER = True  # True to print the file being restored for the weights

logging_dispatcher = {
    "DEBUG": "0",
    "INFO": "1",
    "WARNING": "2",
    "ERROR": "3"
}

loss_dispatcher = {
    'mean_square': loss.mean_square,
    'categorical_crossentropy': loss.categorical_crossentropy
}

act_dispatcher = {
    'linear': act.linear,
    'cart_sigmoid': act.cart_sigmoid,
    'cart_elu': act.cart_elu,
    'cart_exponential': act.cart_exponential,
    'cart_hard_sigmoid': act.cart_hard_sigmoid,
    'cart_relu': act.cart_relu,
    'cart_selu': act.cart_selu,
    'cart_softplus': act.cart_softplus,
    'cart_softsign': act.cart_softsign,
    'cart_tanh': act.cart_tanh,
    'cart_softmax': act.cart_softmax,
    'cart_softmax_real': act.cart_softmax_real
}


class OutputOpts:
    def __init__(self, tensorboard, verbose, save_loss_acc):
        self.tensorboard = tensorboard
        self.verbose = verbose
        self.save_loss_acc = save_loss_acc


def check_tf_version():
    # Makes sure Tensorflow version is 2
    assert tf.__version__.startswith('2')


def check_gpu_compatible():
    print("Available GPU devices:", flush=True)
    print(tf.test.gpu_device_name(), flush=True)
    print("Built in with CUDA: " + str(tf.test.is_built_with_cuda()), flush=True)
    print("GPU available: " + str(tf.test.is_gpu_available()), flush=True)


class Cvnn:
    """-------------------------
    # Constructor and Destructor
    -------------------------"""

    def __init__(self, name, learning_rate=0.001, automatic_restore=True,
                 tensorboard=True, verbose=True, save_loss_acc=True, logging_level="INFO"):
        """
        Constructor
        :param name: Name of the network to be created. This will be used to save data into ./log/<name>/run-{date}/
        :param learning_rate: Learning rate at which the network will train TODO: this should not be here
        :param tensorboard: True if want the network to save tensorboard graph and summary
        :param verbose: True for verbose mode (print and output results)
        :param automatic_restore: True if network should search for saved models (will look for the newest saved model)
        """
        tf.compat.v1.disable_eager_execution()  # This class works as a graph model so no eager compatible
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = logging_dispatcher[logging_level]
        # tf.autograph.set_verbosity(logging.FATAL)       # TODO: not working :S
        # Save parameters of the constructor
        self.name = name
        self.output_options = OutputOpts(tensorboard, verbose, save_loss_acc)
        self.automatic_restore = automatic_restore
        self.learning_rate = learning_rate

        # logs dir
        self.now = datetime.today().strftime("%Y%m%d%H%M%S")
        project_path = os.path.abspath("./")
        self.root_dir = project_path + "/log/{}/run-{}/".format(self.name, self.now)
        # Tensorboard
        self.tbdir = self.root_dir + "tensorboard_logs/"
        if not os.path.exists(self.tbdir):
            os.makedirs(self.tbdir)
        # checkpoint models
        self.savedir = self.root_dir + "saved_models/"
        if not os.path.exists(self.savedir):
            os.makedirs(self.savedir)

        # Launch the graph in a session.
        # self.sess = tf.compat.v1.Session()
        self.restored_meta = False
        if automatic_restore:
            self.restore_graph_from_meta()

        self._save_object_summary(self.root_dir)  # Save info to metadata

    def __del__(self):
        """
        Destructor
        :return: None
        """
        if self.output_options.tensorboard:
            try:
                self.writer.close()
            except AttributeError:
                print("Writer did not exist, couldn't delete it")
        try:  # TODO: better way to do it?
            self.sess.close()
        except AttributeError:
            print("Session was not created")

    """----------------
    # metadata.txt file
    ----------------"""

    def _save_object_summary(self, root_dir):
        """
        Create a .txt inside the root_dir with the information of this object in particular.
        If the file already exists it exits with a fatal message not to override information.
        :param root_dir: Directory path to where the txt file will be saved
        :return: None
        """
        try:
            self.metadata_filename = root_dir + "metadata.txt"
            with open(self.metadata_filename, "x") as file:
                # 'x' mode creates a new file. If file already exists, the operation fails
                file.write(self.name + "\n")
                file.write(self.now + "\n")
                file.write("automatic_restore, " + str(self.automatic_restore) + "\n")
                file.write("Restored," + str(self.restored_meta) + "\n")
                file.write("Tensorboard enabled, " + str(self.output_options.tensorboard) + "\n")
                file.write("Learning Rate, " + str(self.learning_rate) + "\n")
                file.write("Weight initialization, " + "uniform distribution over [0, 1)")
                # TODO: change to correct distr
        except FileExistsError:  # TODO: Check if this is the actual error
            sys.exit("Fatal: Same file already exists. Aborting to not override results")

    def _append_graph_structure(self, shape):
        """
        Appends the shape of the network to the metadata file.
        It checks the meta data file exists, if not throws and error and exits.
        :param shape: Shape of the network to be saved
        :return: None
        """
        if not os.path.exists(self.metadata_filename):
            sys.exit("Cvnn::_append_graph_structure: The meta data file did not exist!")
        with open(self.metadata_filename, "a") as file:
            # 'a' mode Opens a file for appending. If the file does not exist, it creates a new file for writing.
            file.write("\n")
            for i in range(len(shape)):
                fun_name = self._get_func_name(shape[i][1])
                if i == 0:
                    file.write("input layer: " + str(shape[i][0]) + "; act_fun = " + fun_name)
                elif i == len(shape) - 1:
                    file.write("output layer: " + str(shape[i][0]) + "; act_fun = " + fun_name)
                else:
                    file.write("hidden layer: " + str(i) + ", " + str(shape[i][0]) + "; act_fun = " + fun_name)
                file.write("\n")

    """-----------------------
    #          Train 
    -----------------------"""

    def train(self, x_train, y_train, x_test, y_test, epochs=10, batch_size=100, display_freq=1000, normal=False):
        """
        Performs the training of the neural network.
        If automatic_restore is True but not metadata was found,
            it will try to load the weights of the newest previously saved model.
        :param normal: Normalize data before training
        :param x_train: Training data of shape (<training examples>, <input_size>)
        :param y_train: Labels of the training data of shape (<training examples>, <output_size>)
        :param x_test: Test data to display accuracy at the end of shape (<test examples>, <input_size>)
        :param y_test: Test labels of shape (<test examples>, <output_size>)
        :param epochs: Total number of training epochs
        :param batch_size: Training batch size.
            If this number is bigger than the total amount of training examples will display an error
        :param display_freq: Display results frequency.
            The frequency will be for each (epoch * batch_size + iteration) / display_freq
        :return: None
        """
        if np.shape(x_train)[0] < batch_size:  # TODO: make this case work as well. Just display a warning
            sys.exit("Cvnn::train(): Batch size was bigger than total amount of examples")
        if normal:
            x_train = normalize(x_train)  # TODO: This normalize could be a bit different for each and be bad.
            x_test = normalize(x_test)
        with self.sess.as_default():
            assert tf.compat.v1.get_default_session() is self.sess
            self._init_weights()

            # Run validation at beginning
            feed_dict_test = {self.X: x_test, self.y: y_test}
            feed_dict_train = {self.X: x_train, self.y: y_train}
            self.print_validation_loss(x_test, y_test, 0)

            # Run train
            num_tr_iter = int(len(y_train) / batch_size)  # Number of training iterations in each epoch
            for epoch in range(epochs):
                # Randomly shuffle the training data at the beginning of each epoch
                x_train, y_train = randomize(x_train, y_train)
                for iteration in range(num_tr_iter):
                    # Get the batch
                    start = iteration * batch_size
                    end = (iteration + 1) * batch_size
                    x_batch, y_batch = get_next_batch(x_train, y_train, start, end)
                    # Run optimization op (backpropagation)
                    feed_dict_batch = {self.X: x_batch, self.y: y_batch}
                    if (epoch * batch_size + iteration) % display_freq == 0:
                        self.run_checkpoint(epoch, num_tr_iter, iteration, feed_dict_batch)
                    self.sess.run(self.training_op, feed_dict=feed_dict_batch)
                self.save_loss_and_acc(feed_dict_train, feed_dict_test)

            # Run validation at the end
            feed_dict_valid = {self.X: x_test, self.y: y_test}
            loss_valid = self.sess.run(self.loss, feed_dict=feed_dict_valid)
            self.print_validation_loss(x_test, y_test, epoch + 1)
            self.save_model("final", "valid_loss", loss_valid)

    """------------------------
    # Predict models and result
    ------------------------"""

    def predict(self, x):
        """
        Runs a single feedforward computation
        :param x: Input of the network
        :return: Output of the network
        """
        # TODO: Check that x has the correct shape!
        with self.sess.as_default():
            # assert tf.compat.v1.get_default_session() is self.sess
            feed_dict_valid = {self.X: x}
            return self.y_out.eval(feed_dict=feed_dict_valid)

    # TODO: precision, recall, f1_score
    def compute_accuracy(self, x, y):
        with self.sess.as_default():
            # assert tf.compat.v1.get_default_session() is self.sess
            feed_dict_valid = {self.X: x, self.y: y}
            return self.sess.run(self.acc, feed_dict=feed_dict_valid)

    def compute_loss(self, x, y):
        with self.sess.as_default():
            # assert tf.compat.v1.get_default_session() is self.sess
            feed_dict_valid = {self.X: x, self.y: y}
            return self.sess.run(self.loss, feed_dict=feed_dict_valid)

    """-------------
    # Graph creation
    -------------"""

    # Layers
    def _create_dense_layer(self, input_size, output_size, input, layer_number):
        with tf.compat.v1.name_scope("dense_layer_" + str(layer_number)) as scope:
            w = tf.Variable(tf.keras.initializers.GlorotUniform()(shape=(input_size, output_size)),
                            name="weights" + str(layer_number))
            b = tf.Variable(tf.zeros(output_size), name="bias" + str(layer_number))
            if self.output_options.tensorboard:
                tf.compat.v1.summary.histogram('real_weight_' + str(layer_number), w)
                tf.compat.v1.summary.histogram('real_bias_' + str(layer_number), b)
            return tf.add(tf.matmul(input, w), b), [w, b]

    def _create_complex_dense_layer(self, input_size, output_size, input_of_layer, layer_number):
        # TODO: treat bias as a weight. It might optimize training (no add operation, only mult)
        with tf.compat.v1.name_scope("dense_layer_" + str(layer_number)):
            # Create weight matrix initialized randomely from N~(0, 0.01)
            w = tf.Variable(tf.complex(tf.keras.initializers.GlorotUniform()(shape=(input_size, output_size)),
                                       tf.keras.initializers.GlorotUniform()(shape=(input_size, output_size))),
                            name="weights" + str(layer_number))
            b = tf.Variable(tf.complex(tf.zeros(output_size),
                                       tf.zeros(output_size)), name="bias" + str(layer_number))
            if self.output_options.tensorboard:
                tf.compat.v1.summary.histogram('real_weight_' + str(layer_number), tf.math.real(w))
                tf.compat.v1.summary.histogram('imag_weight_' + str(layer_number), tf.math.imag(w))
                tf.compat.v1.summary.histogram('real_bias_' + str(layer_number), tf.math.real(b))
                tf.compat.v1.summary.histogram('imag_bias_' + str(layer_number), tf.math.imag(b))
            return tf.add(tf.matmul(input_of_layer, w), b), [w, b]

    def _create_graph_from_shape(self, shape, input_dtype=np.complex64, output_dtype=np.float32):
        if len(shape) < 2:
            sys.exit("Cvnn::_create_graph_from_shape: shape should be at least of lenth 2")
        # Define placeholders
        self.X = tf.compat.v1.placeholder(tf.dtypes.as_dtype(input_dtype), shape=[None, shape[0][0]], name='X')
        self.y = tf.compat.v1.placeholder(tf.dtypes.as_dtype(output_dtype), shape=[None, shape[-1][0]], name='Y')

        variables = []
        with tf.compat.v1.name_scope("forward_phase"):
            out = self._apply_activation(shape[0][1], self.X)
            for i in range(len(shape) - 1):  # Apply all the layers
                if input_dtype == np.complex64:
                    out, variable = self._create_complex_dense_layer(shape[i][0], shape[i + 1][0], out, i + 1)
                elif input_dtype == np.float32:
                    out, variable = self._create_dense_layer(shape[i][0], shape[i + 1][0], out, i + 1)
                else:  # TODO: add the rest of data types
                    sys.exit("CVNN::_create_graph_from_shape: input_type " + str(input_dtype) + " not supported")
                variables.extend(variable)
                out = self._apply_activation(shape[i + 1][1], out)  # Apply activation function
            y_out = tf.compat.v1.identity(out, name="y_out")
        if tf.dtypes.as_dtype(np.dtype(output_dtype)) != y_out.dtype:  # Case for real output / real labels
            y_out = tf.abs(y_out)  # TODO: Shall I do abs or what?
        self._append_graph_structure(shape)  # Append the graph information to the metadata.txt file
        return y_out, variables

    # Graphs
    def create_mlp_graph(self, loss_func, shape,
                         input_dtype=np.complex64, output_dtype=np.float32):
        """
        Creates a complex-fully-connected dense graph using a shape as parameter
        :param shape: List of tuple
            1. each number of shape[i][0] correspond to the total neurons of layer i.
            2. a string in shape[i][1] corresponds to the activation function listed on
                https://complex-valued-neural-networks.readthedocs.io/en/latest/act_fun.html
            Where i = 0 corresponds to the input layer and the last value of the list corresponds to the output layer.
        :param loss_func:
        :param input_dtype: Set to np.float32 to make a real-valued neural network (output_dtype should also be float32)
        :param output_dtype: Datatype of the output of the network. Normally float32 for classification.
            NOTE: If float32 make sure the last activation function gives a float32 and not a complex32!
        :return: None
        """
        if output_dtype == np.complex64 and input_dtype == np.float32:
            sys.exit("Cvnn::create_mlp_graph: if input dtype is real output cannot be complex")
        if self.restored_meta:
            print("Warning:Cvnn::create_mlp_graph: Graph was already created from a saved model.")
            return None
        # Reset latest graph
        tf.compat.v1.reset_default_graph()

        # Creates the feedforward network
        self.y_out, variables = self._create_graph_from_shape(shape, input_dtype, output_dtype)
        # Defines the loss function
        self.loss = self._apply_loss(loss_func)

        with tf.compat.v1.name_scope("acc_scope"):
            y_prediction = tf.math.argmax(self.y_out, 1)
            y_labels = tf.math.argmax(self.y, 1)
            self.acc = tf.math.reduce_mean(tf.dtypes.cast(tf.math.equal(y_prediction, y_labels), tf.float64))

        # Calculate gradients
        # with tf.compat.v1.name_scope("gradients") as scope:
        gradients = tf.gradients(ys=self.loss, xs=variables)
        # Defines a training operator for each variable
        self.training_op = []
        with tf.compat.v1.variable_scope("learning_rule"):
            # lr_const = tf.constant(self.learning_rate, name="learning_rate")
            for i, var in enumerate(variables):
                # Only gradient descent supported for the moment
                self.training_op.append(tf.compat.v1.assign(var, var - self.learning_rate * gradients[i]))
        # assert len(self.training_op) == len(gradients)

        # logs to be saved with tensorboard
        # TODO: add more info like for ex weights
        if self.output_options.tensorboard:
            self.writer = tf.compat.v1.summary.FileWriter(self.tbdir, tf.compat.v1.get_default_graph())
            loss_summary = tf.compat.v1.summary.scalar(name='Loss', tensor=self.loss)
            acc_summary = tf.compat.v1.summary.scalar(name='Accuracy (%)', tensor=self.acc)
            self.merged = tf.compat.v1.summary.merge_all()

        self.init = tf.compat.v1.global_variables_initializer()
        self.sess = tf.compat.v1.Session()

        # create saver object of the models weights
        self.saver = tf.compat.v1.train.Saver()
        # for i, var in enumerate(self.saver._var_list):
        #     print('Var {}: {}'.format(i, var))

    def create_linear_regression_graph(self, input_size, output_size,
                                       input_dtype=np.complex64, output_dtype=np.float32):
        """
        Creates a linear_regression_graph with no activation function
        :param input_size:
        :param output_size:
        :param input_dtype:
        :param output_dtype:
        :return:
        """
        self.create_mlp_graph(loss.mean_square, [(input_size, act.linear),
                                                 (output_size, act.linear)],
                              input_dtype, output_dtype)

    # Others
    def restore_graph_from_meta(self, latest_file=None):
        """
        Restores an existing graph from meta data file
        :param latest_file: Path to the file to be restored. If no latest_file given and self.automatic_restore is True,
                            the function will try to load the newest metadata inside `saved_models/` folder.
        :return: None
        """
        if latest_file is None and self.automatic_restore:  # Get the metadata file
            if os.listdir(self.savedir + '../../'):
                parent_dir = os.path.abspath(self.savedir + '../../')
                print("Getting last model")
                # get newest folder
                list_of_folders = glob.glob(parent_dir + '/*')
                latest_folder = max(list_of_folders, key=os.path.getctime)
                # get newest file in the newest folder
                list_of_folders.remove(latest_folder)
                while list_of_folders:
                    latest_folder = max(list_of_folders, key=os.path.getctime)
                    # set_trace()
                    # Just take ckpt files, not others.
                    list_of_files = glob.glob(latest_folder + '/saved_models/*.ckpt.meta')
                    if list_of_files:     # If a saved model was found!
                        latest_file = max(list_of_files, key=os.path.getctime)  # .replace('/', '\\')
                        print("Found model " + latest_file)
                        break
                    list_of_folders.remove(latest_folder)
                if latest_file is None:
                    print("Warning:restore_graph_from_meta(): No model found...")
                    return None
            else:
                print('Warning:restore_graph_from_meta(): No model found...')
                return None
        elif latest_file is None:
            sys.exit("Error:restore_graph_from_meta(): no latest_file given and automatic_restore disabled")
        # TODO: check latest_file exists and has the correct format!

        # delete the current graph
        # self.sess.reset_default_graph()

        # import the graph from the file
        imported_graph = tf.compat.v1.train.import_meta_graph(latest_file)
        self.restored_meta = True

        # list all the tensors in the graph
        if DEBUG_RESTORE_META:
            for tensor in tf.compat.v1.get_default_graph().get_operations():
                print(tensor.name)

        with self.sess.as_default():
            imported_graph.restore(self.sess, latest_file.split('.ckpt')[0] + '.ckpt')
            graph = tf.compat.v1.get_default_graph()
            # for op in graph.get_operations():
            #     print(op)
            # set_trace()
            self.loss = graph.get_operation_by_name("loss/loss").outputs[0]
            self.X = graph.get_tensor_by_name("X:0")
            self.y = graph.get_tensor_by_name("Y:0")
            self.y_out = graph.get_tensor_by_name("forward_phase/y_out:0")
            # print(tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.GLOBAL_VARIABLES, "learning_rule"))
            self.training_op = [graph.get_operation_by_name(tensor.name) for tensor in
                                tf.compat.v1.get_default_graph().get_operations()
                                if tensor.name.startswith("learning_rule/AssignVariableOp")]
            # logs
            if self.output_options.tensorboard:
                self.writer = tf.compat.v1.summary.FileWriter(self.tbdir, tf.compat.v1.get_default_graph())
                self.loss_summary = tf.compat.v1.summary.scalar(name='loss_summary', tensor=self.loss)
                self.merged = tf.compat.v1.summary.merge_all()

            # create saver object
            self.saver = tf.compat.v1.train.Saver()
            # for i, var in enumerate(self.saver._var_list):
            #     print('Var {}: {}'.format(i, var))

    def _init_weights(self, latest_file=None):
        """
        Check for any saved weights within the "saved_models" folder.
        If no model available it initialized the weighs itself.
        If the graph was already restored then the weights are already initialized so the function does nothing.
        :return: None
        """
        if not self.restored_meta:
            with self.sess.as_default():
                assert tf.compat.v1.get_default_session() is self.sess
                if latest_file is None and self.automatic_restore:
                    if os.listdir(self.savedir):
                        if self.output_options.verbose:
                            print("Cvnn::init_weights: Getting last model")
                        # get newest folder
                        list_of_folders = glob.glob(self.savedir + '/*')
                        latest_folder = max(list_of_folders, key=os.path.getctime)
                        # get newest file in the newest folder
                        list_of_files = glob.glob(latest_folder + '/*.ckpt.data*')  # Just take ckpt files, not others.
                        # latest_file = max(list_of_files, key=os.path.getctime).replace('/', '\\')
                        # .split('.ckpt')[0] + '.ckpt'
                        latest_file = max(list_of_files, key=os.path.getctime).split('.ckpt')[0] + '.ckpt'
                        if DEBUG_WEIGHT_LOADER:
                            print("Restoring model: " + latest_file)
                        self.saver.restore(self.sess, latest_file)
                    else:
                        if self.output_options.verbose:
                            print("Cvnn::init_weights: No model found.", end='')
                # Check again to see if I found one
                if latest_file is not None:  # TODO: check file exists and has correct format!
                    if DEBUG_WEIGHT_LOADER:
                        print("Restoring model: " + latest_file)
                    self.saver.restore(self.sess, latest_file)
                else:
                    if self.output_options.verbose:
                        print("Initializing weights...")
                    self.sess.run(self.init)

    """-----------------
    # Checkpoint methods
    -----------------"""

    def run_checkpoint(self, epoch, num_tr_iter, iteration, feed_dict_batch):
        """
        Calculate and display the batch loss and accuracy. Saves data to tensorboard and saves state of the network
        :param epoch:
        :param num_tr_iter:
        :param iteration:
        :param feed_dict_batch:
        :return:
        """
        loss_batch = self.sess.run(self.loss, feed_dict=feed_dict_batch)
        acc_batch = self.sess.run(self.acc, feed_dict=feed_dict_batch)
        if self.output_options.verbose:
            print("epoch {0:3d}:\t iteration {1:3d}: \t Loss={2:.2f}\t Acc={3:.2f}".format(epoch, iteration,
                                                                                           loss_batch, acc_batch))
        # save the model
        self.save_model(epoch, iteration, loss_batch)
        self._save_to_tensorboard(epoch, num_tr_iter, iteration, feed_dict_batch)

    def _save_to_tensorboard(self, epoch, num_tr_iter, iteration, feed_dict_batch):
        with self.sess.as_default():
            assert tf.compat.v1.get_default_session() is self.sess
            if self.output_options.tensorboard:  # Save only if needed
                # add the summary to the writer (i.e. to the event file)
                step = epoch * num_tr_iter + iteration
                summary = self.sess.run(self.merged, feed_dict=feed_dict_batch)
                self.writer.add_summary(summary, step)

    def save_model(self, epoch, iteration, loss_batch):
        """

        :param epoch:
        :param iteration:
        :param loss_batch:
        :return:
        """
        modeldir = "{}epoch{}-iteration{}-loss{}.ckpt".format(self.savedir, epoch, iteration,
                                                              str(loss_batch).replace('.', ','))
        saved_path = self.saver.save(self.sess, modeldir)
        # print('model saved in {}'.format(saved_path))

    def save_loss_and_acc(self, feed_dict_train, feed_dict_test):
        if self.output_options.save_loss_acc:
            loss_batch = self.sess.run(self.loss, feed_dict=feed_dict_train)
            acc_batch = self.sess.run(self.acc, feed_dict=feed_dict_train)
            loss_test = self.sess.run(self.loss, feed_dict=feed_dict_test)
            acc_test = self.sess.run(self.acc, feed_dict=feed_dict_test)

            write = True
            if os.path.exists(self.root_dir + self.name + '.csv'):
                write = False
            file = open(self.root_dir + self.name + '.csv', 'a')
            if write:
                file.write("train loss,train acc,test loss,test acc\n")
                self.saved_loss_acc_vectors = {
                    "train_loss": [],
                    "train_acc": [],
                    "test_loss": [],
                    "test_acc": []
                }
            file.write(str(loss_batch) + "," + str(acc_batch) + "," + str(loss_test) + "," + str(acc_test) + "\n")
            self.saved_loss_acc_vectors["train_loss"].append(loss_batch)
            self.saved_loss_acc_vectors["train_acc"].append(acc_batch)
            self.saved_loss_acc_vectors["test_loss"].append(loss_test)
            self.saved_loss_acc_vectors["test_acc"].append(acc_test)
        return None

    """-------------------
    # Apply functions
    -------------------"""

    @staticmethod
    def _get_func_name(fun):
        if callable(fun):
            return fun.__name__
        elif isinstance(fun, str):
            return fun
        else:
            sys.exit("Error::_get_func_name: Function not recognizable")

    @staticmethod
    def _apply_activation(act_fun, out):
        """
        Applies activation function `act` to variable `out`
        :param out: Tensor to whom the activation function will be applied
        :param act_fun: function to be applied to out. See the list fo possible activation functions on:
            https://complex-valued-neural-networks.readthedocs.io/en/latest/act_fun.html
        :return: Tensor with the applied activation function
        """
        if callable(act_fun):
            if act_fun.__module__ == 'activation_functions' or \
                    act_fun.__module__ == 'tensorflow.python.keras.activations':
                return act_fun(out)  # TODO: for the moment is not be possible to give parameters like alpha
            else:
                sys.exit("Cvnn::_apply_activation Unknown loss function.\n\t "
                         "Can only use activations declared on activation_functions.py or keras.activations")
        elif isinstance(act_fun, str):
            try:
                return act_dispatcher[act_fun](out)
            except KeyError:
                print("WARNING: Cvnn::_apply_function: " + str(act_fun) + " is not callable, ignoring it")
            return out

    def _apply_loss(self, loss_func):
        # TODO: don't like the fact that I have to give self to this and not to apply_activation
        if callable(loss_func):
            if loss_func.__module__ != 'losses' and loss_func.__module__ != 'tensorflow.python.keras.losses':
                sys.exit("Cvnn::_apply_loss: Unknown loss function.\n\t "
                         "Can only use losses declared on losses.py or tensorflow.python.keras.losses")
        elif isinstance(loss_func, str):
            try:
                loss_func = loss_dispatcher[loss_func]
            except KeyError:
                sys.exit("Cvnn::_apply_loss: Invalid loss function name")
        else:
            sys.exit("Cvnn::_apply_loss: Invalid loss function")

        return tf.reduce_mean(input_tensor=loss_func(self.y, self.y_out), name=loss_func.__name__)

    """------------
    # Data Analysis
     -----------"""

    def print_validation_loss(self,  x, y, epoch=None):
        feed_dict_valid = {self.X: x, self.y: y}
        loss_valid = self.sess.run(self.loss, feed_dict=feed_dict_valid)
        acc_valid = self.sess.run(self.acc, feed_dict=feed_dict_valid)
        print('---------------------------------------------------------')
        if epoch is not None:
            print("Epoch: {0}, validation loss: {1:.4f}, accuracy: {2:.4f}".format(epoch, loss_valid, acc_valid))
        else:
            print("Loss: {1:.4f}, Accuracy: {2:.4f}".format(epoch, loss_valid, acc_valid))
        print('---------------------------------------------------------')

    def confusion_matrix(self, x_test, y_test):
        print(da.categorical_confusion_matrix(self.predict(x_test), y_test, None))

    def plot_loss_and_acc(self):
        self.plot_loss()
        self.plot_acc()
        return

    def plot_loss(self):
        if self.output_options.save_loss_acc:
            plt.figure()
            plt.plot(range(len(self.saved_loss_acc_vectors["train_loss"])),
                     self.saved_loss_acc_vectors["train_loss"],
                     'o-',
                     label='train loss')
            plt.plot(range(len(self.saved_loss_acc_vectors["test_loss"])),
                     self.saved_loss_acc_vectors["test_loss"],
                     '^-',
                     label='test loss')
            plt.legend(loc="upper right")
            plt.ylabel("epochs")
            plt.xlabel("loss")
            plt.title("Train vs Test loss")
            plt.show()
        else:
            print("save_loss_acc was disabled. No data was saved in order to plot the graph. "
                  "Next time create your model with save_loss_acc = True")

    def plot_acc(self):
        if self.output_options.save_loss_acc:
            plt.figure()
            plt.plot(range(len(self.saved_loss_acc_vectors["train_acc"])),
                     self.saved_loss_acc_vectors["train_acc"],
                     'o-',
                     label='train acc')
            plt.plot(range(len(self.saved_loss_acc_vectors["test_acc"])),
                     self.saved_loss_acc_vectors["test_acc"],
                     '^-',
                     label='test acc')
            plt.legend(loc="lower right")
            plt.ylabel("epochs")
            plt.xlabel("accuracy (%)")
            plt.title("Train vs Test accuracy")
            plt.show()
        else:
            print("save_loss_acc was disabled. No data was saved in order to plot the graph. "
                  "Next time create your model with save_loss_acc = True")


if __name__ == "__main__":
    # monte_carlo_loss_gaussian_noise(iterations=100, filename="historgram_gaussian.csv")
    m = 100000
    n = 100
    num_classes = 5
    x_train, y_train, x_test, y_test = dp.get_gaussian_noise(m, n, num_classes, 'hilbert')

    # Network Declaration
    auto_restore = False
    cvnn = Cvnn("CVNN_testing", automatic_restore=auto_restore, logging_level="INFO")

    input_size = np.shape(x_train)[1]
    hidden_size = 10
    output_size = np.shape(y_train)[1]
    # cvnn.create_linear_regression_graph(input_size, output_size)
    cvnn.create_mlp_graph("categorical_crossentropy",
                          [(input_size, 'ignored'),
                           (hidden_size, 'cart_sigmoid'),
                           (output_size, 'cart_softmax_real')])

    cvnn.train(x_train, y_train, x_test, y_test)

    print(da.categorical_confusion_matrix(cvnn.predict(x_test), y_test, "output.png"))
    cvnn.plot_loss()
    set_trace()

    # TODO: it will be a good idea to make a test program to make sure my network is still working when I do changes

    """y_out = cvnn.predict(x_test)
    if y_out is not None:
        print(y_out[:3])
        print(y_test[:3])"""

# How to comment script header
# https://medium.com/@rukavina.andrei/how-to-write-a-python-script-header-51d3cec13731
__author__ = 'J. Agustin BARRACHINA'
__copyright__ = 'Copyright 2020, {project_name}'
__credits__ = ['{credit_list}']
__license__ = '{license}'
__version__ = '0.0.14'
__maintainer__ = 'J. Agustin BARRACHINA'
__email__ = 'joseagustin.barra@gmail.com; jose-agustin.barrachina@centralesupelec.fr'
__status__ = '{dev_status}'