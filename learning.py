#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This file contains the main algorithm process for
LSTM and Neural Net combinations on Wikipedia Data.
Functions defined here require results input in the
specific format. With the training and test results,
these functions perform the remaining operations as required.

These functions rely on LSTM and DNN classes from
lstm.py and nn_base.py respectively

Special libraries required: numpy
Standard libraries used: json, os, pickle, random, time

Primary functions:
    - train_nn_using_k_lstm_bit
    - test_nn_using_k_lstm_bit
    - train_nn_only
    - test_nn_only

- Rakshit Agrawal, 2016
"""

import json
import os
import pickle
import random
import numpy as np
import time

from lstm import LSTM
from nn_base import DNN

# Number of hidden layers in LSTM
from serializer import data_to_json

M = 12

# Number of features present per revision
Nf_quality = 14
Nf_existence = 15


def _learning_factor(weight_value):
    """
    Provide a learning factor which is a function of
    the size of update
    :param weight_value: Size of update
    :return: Learning factor for the update
    """
    return np.square(weight_value)


def _train_nn_with_k_lstm_bits(data_list,
                               k=None,
                               N=1000,
                               quality=True,
                               fix_bit_val=None,
                               weighted_learning=False):
    """

    Get the items of dict of authors with each value containing:
     author, (matrix_of 0:n-1 revisions with features and quality,
      features of nth revision without quality,
      quality of nth revision
    )

    For a given number N of iterations:
        For each author now, run the author's results (0-n-1) revisions
        through the LSTM. From the LSTM extract k bits of output and
        send them along with nth revision's features to the Neural Net.
        Output from the Neural Net is then compared with our target value
        and loss is pushed back to Neural Net for backpropagation.
        The Neural net then provides \partial loss / \partial input for
        every input  to it. The returned values from it corresponding to
        the LSTM's k bits are then fed back through the LSTM to perform
        a backward using AdaDelta algorithm.

    :param data_list: This list contains all items in structure (author, (x_mat, fy, yt))
    :param k: Number of bits to be used
    :param N: Number of iterations for training
    :param quality: Boolean to control if working on quality, otherwise existence
    :param fix_bit_val: Fixed value of bit to be used if only that bit should be passed to NN
    :param weighted_learning: Boolena to control weighted learning. Default is False
    :return: (Trained LSTM, Trained NNet), List of errors
    """

    Nf = Nf_quality if quality else Nf_existence
    # Initialize an LSTM
    lstm = LSTM()
    lstm.initialize(Nf, M)
    learning_factor = 1.0

    # Initialize a Neural Network
    nnet = DNN()

    # NN will take input from it's inputs + k bits.
    # Value of middle layer in NN is set with different experiments (can be changed)
    # NN will give 1 output (for quality of revision)
    if k is not None:
        nnet.initialize([k + 12, k + 12 + (M / 2), 1])
    else:
        nnet.initialize([12 + 12, 12 + 12 + (M / 2), 1])

    iter_ctr = N
    # Perform the following for N iterations
    for iteration in range(N):

        # Shuffle the positions of results
        random.shuffle(data_list)

        # Create empty list for collecting errors, predicted outputs
        errors = np.array([])

        # Start the process for each author
        for cnt, (author, (x_mat, fy, yt)) in enumerate(data_list):

            # Ignore if target doesn't exist
            if not yt:
                continue

            Y = np.array([])
            if (k > 0 or k is None) and fix_bit_val is None:
                # Run LSTM only if bits from LSTM are required
                # Send x features to the wikipedia_lstm and collect output in Y
                Y = lstm.forward(x_mat)

            # Set the input for NNet using k bits of Y
            nnet_input = np.concatenate((Y[:k], fy)) if fix_bit_val is None else np.concatenate(
                (np.array(fix_bit_val), fy))

            # Sending input to NNet
            y = nnet.forward(nnet_input)

            if (k > 0 or k is None) and quality:
                # Quality normalized
                yt = 1.0 * (yt + 1.0) / 2.0

            # Measure squared loss
            e = np.sum((y - yt) ** 2)
            dy = 2.0 * (y - yt)

            # Add loss to error list
            errors = np.append(errors, e)

            # Now send the loss through NN backpropagation
            bp_res = nnet.backward_adadelta(dy)

            if k > 0 or k is None:
                # Send through LSTM only if its bits count
                # Generate input for LSTM backward round
                back_el = np.zeros(Y.shape)
                bp_res = np.resize(bp_res, Y.shape)
                back_el[:k] = bp_res[:k]

                # Send the result on bit back through the LSTM
                if weighted_learning:
                    # Get update size using average of this revision's
                    # char added and char subtracted (fy[3] and fy[4])
                    update_size = np.average((fy[3], fy[4]))
                    learning_factor = _learning_factor(update_size)

                lstm.backward_adadelta(back_el, learning_factor=learning_factor)

        # Print average error
        iter_ctr += 1
        if iter_ctr >= N / 100:
            avg_error = np.average(errors)
            print"Avg Err at %r iteration, for all users: %r " % (iteration, avg_error)
            iter_ctr = 0

        # Print on last iteration
        if iteration == N - 1:
            avg_error = np.average(errors)
            print"Avg Err at %r iteration, for all users: %r " % (iteration, avg_error)

    return (lstm, nnet), errors


def _test_nn_with_k_lstm_bits(test_data, lstm, nnet, k=None, quality=True, fix_bit_val=None):
    """

    Get the dict of authors as keys and values in form:
     (matrix_of 0:n-1 revisions with features and quality,
      features of nth revision without quality,
      quality of nth revision
    )

    Now pass it through trained LSTM and Neural net combination which has been
    For each author,
        run the author's results (0-n-1) revisions
        through the LSTM. From the LSTM extract k bits of output and
        send them along with nth revision's features to the Neural Net.
        Output from the Neural Net is then compared with our target value
        and loss is reported.
        Add the loss, true label and predicted label to respective lists
        Also add a weighing factor to list of weights which corresponds
        to the size of update

    :param test_data: Dict containing items in structure (author, (x_mat, fy, yt))
    :param lstm: Trained LSTM
    :param nnet: Trained Neural Net
    :param k: Number of bits to be used
    :return: Errors, True labels, Predicted labels
    """

    # Get items from dict
    items = test_data.items()

    # Create empty lists for errors, lables and weights
    errors = np.array([])
    y_true = np.array([])
    y_pred = np.array([])
    label_weights = np.array([])

    print "\n\n==Validation==\n\n"

    # Start the process for each author
    for cnt, (author, (x_mat, fy, yt)) in enumerate(items):

        # Check to ignore entry in absence of target value
        if not yt:
            continue
        Y = np.array([])
        if (k > 0 or k is None) and fix_bit_val is None:
            # Run LSTM only if bits from LSTM are required
            # Send x features to the wikipedia_lstm and collect output in Y
            Y = lstm.forward(x_mat)

        # Set the input for NNet using k bits of Y
        nnet_input = np.concatenate((Y[:k], fy)) if fix_bit_val is None else np.concatenate(
            (np.array([fix_bit_val]), fy))

        # Sending LSTM output bit combined with last revisions features to Nnet
        y = nnet.forward(nnet_input)

        if k > 0 or k is None and quality:
            # Quality normalized
            yt = 1.0 * (yt + 1.0) / 2.0

        # Measure error
        e = np.sum((y - yt) ** 2)

        # Append error and target entries into corresponding lists
        errors = np.append(errors, e)
        y_pred = np.append(y_pred, y)
        y_true = np.append(y_true, yt)

        # Get update size using average of this revision's
        # char added and char subtracted (fy[3] and fy[4])
        update_size = np.average((fy[3], fy[4]))
        label_weights = np.append(label_weights, update_size)

    print "Average validation error: ", np.average(errors)

    # Return the computed labels along with errors, true labels and weights
    return errors, y_pred, y_true, label_weights


def train_nn_using_k_lstm_bit(train_dict,
                              k=None,
                              N=1000,
                              quality=True,
                              fix_bit_val=None,
                              store=False,
                              picklefile=os.path.join(os.getcwd(), 'results', 'temp_model.pkl'),
                              weighted_learning=False,
                              balanced=True):
    """
    Train the LSTM and NNet combination using training dict.

    :param train_dict: dict containing entries of revisions per user
    :param k: Number of bits to be used from LSTM
    :param N: Number of iterations for network to train. Default is 1000
    :param quality: Boolean to control if working on quality, otherwise existence
    :param fix_bit_val: Fixed value of bit to be used if only that bit should be passed to NN
    :param store: Boolean to decide whether to store result in pickle
    :param picklefile: Pickle filename
    :param weighted_learning: Boolean to control whether learning is weighted or not
    :param balanced: Boolean to control whether results should be balanced before use or not
    :rtype tuple
    :return: Returns a tuple consisting of lstm and neural net (lstm, nnet)
    """
    train_items = train_dict.items()
    if balanced:
        train_items = _rebalance_data(train_items)

    # Send for training using k as no. of bits to use
    print "\n==Starting training== (Using %r iterations) and k=%r" % (N, k)
    print "Statuses-- Weighted: %r, Balanced %r" % (weighted_learning, balanced)
    t_start = time.clock()
    (lstm_out, nn_out), errors = _train_nn_with_k_lstm_bits(train_items, k=k, N=N, fix_bit_val=fix_bit_val,
                                                            weighted_learning=weighted_learning, quality=quality)
    print "Training completed in %r seconds" % (time.clock() - t_start)

    # Store the trained model into a pickle if store is True
    if store:
        file_basic_name = 'trained_lstm_%r_nn_%r_%r' % (k, N, "weighted" if weighted_learning else "unweighted")
        serialize_file_lstm = os.path.join(os.getcwd(), 'results', file_basic_name + 'lstm.json')
        serialize_file_nn = os.path.join(os.getcwd(), 'results', file_basic_name + 'nn.json')
        from json_plus import Serializable
        ser_result_lstm = Serializable.dumps(lstm_out)
        ser_result_nn = Serializable.dumps(nn_out)

        with open(serialize_file_lstm, 'wb') as output:
            json.dump(ser_result_lstm, output)
        with open(serialize_file_nn, 'wb') as output:
            json.dump(ser_result_nn, output)

        # Store the (lstm, nnet) type result into a pickle
        with open(picklefile, 'wb') as output:
            pickle.dump((lstm_out, nn_out), output, pickle.HIGHEST_PROTOCOL)

    return (lstm_out, nn_out)


def _expand_to_all(items):
    """
    For NN only case, instead of using only last edit for training,
    use each and every edit by every user. Using full results basically
    :param train_items:
    :return:
    """
    new_items = []
    empty_mat = np.array([])
    for cnt, (author, (x_mat, fy, yt)) in enumerate(items):
        # Break into xmat
        for row in x_mat:
            new_items.append((author, (empty_mat, row[:-2], row[-1])))
        yt = 1.0 * (yt + 1.0) / 2.0
        new_items.append((author, (empty_mat, fy, yt)))

    return new_items


def _rebalance_data(items):
    """
    Rebalance the biased results to a balanced set where probability
    of each label is 0.5

    While using all negative results, add randomly selected equal
    number of results from other set

    :param train_items:
    :return:
    """
    neg_items = [(author, (x_mat, fy, yt)) for (author, (x_mat, fy, yt)) in items if yt < 0.5]
    pos_items = [(author, (x_mat, fy, yt)) for (author, (x_mat, fy, yt)) in items if yt > 0.5]

    if len(neg_items) <= len(pos_items):
        pos_items = random.sample(pos_items, len(neg_items))
    else:
        neg_items = random.sample(neg_items, len(pos_items))

    new_items = neg_items + pos_items
    print len(neg_items)
    print len(new_items)

    # Shuffle 5 times to ensure mix of results
    for i in range(5):
        np.random.shuffle(new_items)
    return new_items


def train_nn_only(train_dict,
                  N=1000,
                  store=False,
                  picklefile=os.path.join(os.getcwd(), 'results', 'temp_model.pkl'),
                  weighted_learning=False):
    """
    Train the LSTM and NNet combination using training dict.

    :param train_dict: dict containing entries of revisions per user
    :param k: Number of bits to be used from LSTM
    :param N: Number of iterations for network to train. Default is 1000
    :param store: Boolean to decide whether to store result in pickle
    :param picklefile: Pickle filename
    :return: Returns a tuple consisting of lstm and neural net (lstm, nnet)
    """
    train_items = train_dict.items()

    train_items = _expand_to_all(train_items)
    train_items = _rebalance_data(train_items)

    # Send for training using k as no. of bits to use
    print "\n==Starting training== (Using %r iterations)" % (N)
    print "Statuses-- Weighted: %r" % (weighted_learning,)

    t_start = time.clock()
    (lstm_out, nn_out), errors = _train_nn_with_k_lstm_bits(train_items, k=0, N=N, weighted_learning=weighted_learning)
    print "Training completed in %r seconds" % (time.clock() - t_start)

    # Store the trained model into a pickle if store is True
    if store:
        # file_basic_name = 'trained_nn_only_%r_' % (N)
        # serialize_file_lstm = os.path.join(os.getcwd(), 'results', file_basic_name + 'lstm.json')
        # serialize_file_nn = os.path.join(os.getcwd(), 'results', file_basic_name + 'nn.json')
        # from json_plus import Serializable
        # ser_result_lstm = Serializable.dumps(lstm_out)
        # ser_result_nn = Serializable.dumps(nn_out)
        #
        # with open(serialize_file_lstm, 'wb') as output:
        #     json.dump(ser_result_lstm, output)
        # with open(serialize_file_nn, 'wb') as output:
        #     json.dump(ser_result_nn, output)

        # Store the (lstm, nnet) type result into a pickle
        with open(picklefile, 'wb') as output:
            pickle.dump((lstm_out, nn_out), output, pickle.HIGHEST_PROTOCOL)

    return (lstm_out, nn_out)


def _error_measurement(y_pred, y_true, label_weights):
    """
    Provide measurements as requested for the given set of labels

    :param y_pred: List of predicted labels
    :param y_true: List of corresponding true labels
    :param label_weights: Weights associated with each label depending on contribution's size
    :return:
    """

    # Create classification buckets from labels
    Y_pred = [1 if i < 0.5 else 0 for i in y_pred]
    Y_true = [1 if i < 0.5 else 0 for i in y_true]

    print Y_pred
    print Y_true
    from sklearn.metrics import precision_recall_fscore_support, precision_score, recall_score, f1_score, fbeta_score
    (precision, recall, fscore, support) = precision_recall_fscore_support(np.array(Y_true), np.array(Y_pred))
    # average='binary')

    prec_score = precision_score(np.array(Y_true), np.array(Y_pred))
    rec_score = recall_score(np.array(Y_true), np.array(Y_pred))
    fs = f1_score(np.array(Y_true), np.array(Y_pred))

    print "Prec:", prec_score
    print "Rec:", rec_score
    print "F1-score:", fs

    return precision, recall, fscore


def test_nn_using_k_lstm_bit(test_dict, lstm, nnet, k=None, quality=True):
    """

    :param test_dict:
    :return:
    """
    # serialize_file_lstm = os.path.join(os.getcwd(), 'results','ser_file_lstm.json')
    # serialize_file_nn = os.path.join(os.getcwd(), 'results','ser_file_nn.json')
    # from json_plus import Serializable
    #
    # with open(serialize_file_lstm, 'rb') as input:
    #     lstm = Serializable.loads(json.load(input))
    # with open(serialize_file_nn, 'rb') as input:
    #     nnet = Serializable.loads(json.load(input))

    # Send test results with trained model for testing
    errors, y_pred, y_true, label_weights = _test_nn_with_k_lstm_bits(test_dict, lstm, nnet, k=k, quality=quality)

    precision, recall, f_score = _error_measurement(y_pred, y_true, label_weights)

    print "Precision: ", precision, "\tRecall:", recall, "\tFscore: ", f_score

    print "Using value 0 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1, bit_val=0)
    print "Using value 1 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1,bit_val=1)

    return locals()


def test_nn_only(test_dict, lstm, nnet, fix_bit_val=None):
    """

    :param test_dict:
    :return:
    """
    # serialize_file_lstm = os.path.join(os.getcwd(), 'results','ser_file_lstm.json')
    # serialize_file_nn = os.path.join(os.getcwd(), 'results','ser_file_nn.json')
    # from json_plus import Serializable
    #
    # with open(serialize_file_lstm, 'rb') as input:
    #     lstm = Serializable.loads(json.load(input))
    # with open(serialize_file_nn, 'rb') as input:
    #     nnet = Serializable.loads(json.load(input))

    # Send test results with trained model for testing
    errors, y_pred, y_true, label_weights = _test_nn_with_k_lstm_bits(test_dict, lstm, nnet, k=0, fix_bit_val=fix_bit_val)

    precision, recall, f_score = _error_measurement(y_pred, y_true, label_weights)

    print "Precision: ", precision, "\tRecall:", recall, "\tFscore: ", f_score

    print "Using value 0 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1, bit_val=0)
    print "Using value 1 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1,bit_val=1)

    return locals()


def test_random(test_dict):
    """
    Randomly select labels for each entry.
    Used just to measure the scores when predicting from data at random.

    :param test_dict: Dict holding the elements with their true labels
    :return:
    """
    # serialize_file_lstm = os.path.join(os.getcwd(), 'results','ser_file_lstm.json')
    # serialize_file_nn = os.path.join(os.getcwd(), 'results','ser_file_nn.json')
    # from json_plus import Serializable
    #
    # with open(serialize_file_lstm, 'rb') as input:
    #     lstm = Serializable.loads(json.load(input))
    # with open(serialize_file_nn, 'rb') as input:
    #     nnet = Serializable.loads(json.load(input))

    # Send test results with trained model for testing
    y_true = [0 if int(yt) < 0 else 1 for (author, (x_mat, fy, yt)) in test_dict.items()]
    y_pred = [random.choice([0, 1]) for i in range(len(y_true))]
    label_weights = [1.0 for i in range(len(y_true))]
    # errors, y_pred, y_true, label_weights = _test_nn_with_k_lstm_bits(test_dict, lstm, nnet, k=0)

    precision, recall, f_score = _error_measurement(y_pred, y_true, label_weights)

    print "Precision: ", precision, "\tRecall:", recall, "\tFscore: ", f_score

    print "Using value 0 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1, bit_val=0)
    print "Using value 1 for the bit"
    # net_result = _combined_ops_nn_using_k_bits_test([item1], st=0,k=1,bit_val=1)

    return locals()


if __name__ == "__main__":
    print "Starting"
