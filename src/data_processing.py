# -*- coding: utf-8 -*-
from utils import *
import numpy as np
import sys
import os
from os.path import join
from math import sqrt
from scipy.io import loadmat
from scipy import signal
from pdb import set_trace

"""
This files contains all functions used for pre-processing data before training which includes:
    1. Separating into train and test cases with it's corresponding cases (Utils)
    2. Create own dataset (Crate dataset)
    3. Load and save data files (Save and Load data)
"""

"""----
# Utils
----"""


def get_real_train_and_test(x_train, x_test):
    x_train_real = transform_to_real(x_train)
    x_test_real = transform_to_real(x_test)

    return x_train_real, x_test_real


def separate_into_train_and_test(x, y, ratio=0.8, pre_rand=True):
    """
    Separates data x with corresponding labels y into train and test set.
    :param x: data
    :param y: labels of data x
    :param ratio: value between 0 and 1.
        1 meaning all the data x will be the training set and 0 meaning all data x will be the test set.
    :param pre_rand: if True then x and y will be shuffled first (maintaining coherence between them)
    :return: tuple (x_train, y_train, x_test, y_test) of the training and test set both data and labels.
    """
    if (ratio > 1) or (ratio < 0):
        sys.exit("Error:separate_into_train_and_test: ratio should be between 0 and 1. Got value " + str(ratio))
    if pre_rand:
        x, y = randomize(x, y)
    m = np.shape(x)[0]
    x_train = x[:int(m*ratio)]
    y_train = y[:int(m*ratio)]
    x_test = x[int(m*ratio):]
    y_test = y[int(m*ratio):]
    return x_train, y_train, x_test, y_test


def sparse_into_categorical(spar, num_classes=None):
    assert len(spar.shape) == 1
    if num_classes is None:
        num_classes = max(spar) + 1     # assumes labels starts at 0
    cat = np.zeros((spar.shape[0], num_classes))
    for i, k in enumerate(spar):
        cat[i][k] = 1
    return cat


"""-------------
# Create dataset
-------------"""


def _create_non_correlated_gaussian_noise(m, n, mu, sigma):
    """
    Creates a numpy matrix of size mxn with random gaussian distribution of mean mu and variance sigma
    """
    x = (np.random.normal(mu, sigma, (m, n)) + 1j * np.random.normal(mu, sigma, (m, n))) / sqrt(2)
    return x


def _create_hilbert_gaussian_noise(m, n, mu, sigma):
    x_real = np.random.normal(mu, sigma, (m, n))
    return signal.hilbert(x_real)


noise_gen_dispatcher = {
    'non_correlated': _create_non_correlated_gaussian_noise,
    'hilbert': _create_hilbert_gaussian_noise
}


def _create_gaussian_noise(m, n, num_classes=2, noise_type='hilbert'):
    """
    :param m: Number of examples per class
    :param n: Size of vector
    :param num_classes: Number of different classes to be made
    :return: tuple of a (num_classes*m)xn matrix with data and labels regarding it class.
    """
    x = np.empty((num_classes*m, n)) + 1j*np.empty((num_classes*m, n))
    # I am using zeros instead of empty because although counter intuitive it seams it works faster:
    # https://stackoverflow.com/questions/55145592/performance-of-np-empty-np-zeros-and-np-ones
    # DEBUNKED? https://stackoverflow.com/questions/52262147/speed-of-np-empty-vs-np-zeros?
    y = np.zeros((num_classes*m, num_classes))      # Initialize all at 0 to later put a 1 on the corresponding place
    for k in range(num_classes):
        mu = int(100*np.random.rand())
        sigma = 15*np.random.rand()
        print("Class " + str(k) + ": mu = " + str(mu) + "; sigma = " + str(sigma))
        try:
            x[k*m:(k+1)*m, :] = noise_gen_dispatcher[noise_type](m, n, mu, sigma)
        except KeyError:
            sys.exit("_create_gaussian_noise: Unknown type of noise")
        y[k*m:(k+1)*m, k] = 1

    return normalize(x), y


def _create_constant_classes(m, n, num_classes=2, vect=None):
    assert len(vect) == num_classes     # TODO: message of error
    x = np.empty((num_classes * m, n)) + 1j * np.empty((num_classes * m, n))
    y = np.zeros((num_classes * m, num_classes))  # Initialize all at 0 to later put a 1 on the corresponding place
    for k in range(num_classes):
        if vect is None:
            const = np.random.randint(100)
        else:
            const = vect[k]
        x[k * m:(k + 1) * m, :] = np.ones((m, n))*const + 1j * np.ones((m, n))*const
        y[k * m:(k + 1) * m, k] = 1
        print("Class " + str(k) + " value = " + str(const))
    # set_trace()
    return normalize(x), y


def get_non_correlated_gaussian_noise(m, n, num_classes=2):
    return get_gaussian_noise(m, n, num_classes=num_classes, noise_type='non_correlated')


def get_gaussian_noise(m, n, num_classes=2, noise_type='hilbert'):
    x, y = _create_gaussian_noise(m, n, num_classes, noise_type)
    x, y = randomize(x, y)
    return separate_into_train_and_test(x, y)


def get_constant(m, n, num_classes=2, vect=None):
    x, y = _create_constant_classes(m, n, num_classes, vect)
    x, y = randomize(x, y)
    return separate_into_train_and_test(x, y)


"""-----------------
# Save and Load data
-----------------"""


def save_npy_array(array_name, array):
    np.save("../data/"+array_name+".npy", array)


def save_dataset(array_name, x_train, y_train, x_test, y_test):
    """
    Saves in a single .npz file the test and training set with corresponding labels
    :param array_name: Name of the array to be saved into data/ folder.
    :param x_train:
    :param y_train:
    :param x_test:
    :param y_test:
    :return: None
    """
    if not os.path.exists("../data"):
        os.makedirs("../data")
    return np.savez("../data/"+array_name, x_train=x_train, y_train=y_train, x_test=x_test, y_test=y_test)


def load_dataset(array_name):
    """
    Gets all x_train, y_train, x_test, y_test from a previously saved .npz file with save_dataset function.
    :param array_name: name of the file saved in '../data' with .npz termination
    :return: tuple (x_train, y_train, x_test, y_test)
    """
    try:
        # print(os.listdir("../data"))
        npzfile = np.load("../data/" + array_name + ".npz")
        # print(npzfile.files)
        return npzfile['x_train'], npzfile['y_train'], npzfile['x_test'], npzfile['y_test']
    except FileNotFoundError:
        sys.exit("Cvnn::load_dataset: The file could not be found")     # TODO: check if better just throw a warning


def load_matlab_matrices(fname="data_cnn1dT.mat", path="/media/barrachina/data/gilles_data/"):
    mat_fname = join(path, fname)
    mat = loadmat(mat_fname)
    return mat

"""----------------
# Testing Functions
----------------"""


def test_save_load():
    # Data pre-processing
    m = 5000
    n = 30
    input_size = n
    output_size = 1
    total_cases = 2 * m
    train_ratio = 0.8
    # x_train, y_train, x_test, y_test = dp.get_non_correlated_gaussian_noise(m, n)

    x_input = np.random.rand(total_cases, input_size) + 1j * np.random.rand(total_cases, input_size)
    w_real = np.random.rand(input_size, output_size) + 1j * np.random.rand(input_size, output_size)
    desired_output = np.matmul(x_input, w_real)  # Generate my desired output

    # Separate train and test set
    x_train = x_input[:int(train_ratio * total_cases), :]
    y_train = desired_output[:int(train_ratio * total_cases), :]
    x_test = x_input[int(train_ratio * total_cases):, :]
    y_test = desired_output[int(train_ratio * total_cases):, :]

    save_dataset("linear_output", x_train, y_train, x_test, y_test)
    x_loaded_train, y_loaded_train, x_loaded_test, y_loaded_test = load_dataset("linear_output")

    if np.all(x_train == x_loaded_train):
        if np.all(y_train == y_loaded_train):
            if np.all(x_test == x_loaded_test):
                if np.all(y_test == y_loaded_test):
                    print("All good!")


# if __name__ == "__main__":

__author__ = 'J. Agustin BARRACHINA'
__version__ = '0.0.8'
__maintainer__ = 'J. Agustin BARRACHINA'
__email__ = 'joseagustin.barra@gmail.com; jose-agustin.barrachina@centralesupelec.fr'
