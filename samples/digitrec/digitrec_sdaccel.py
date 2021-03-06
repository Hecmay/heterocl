# -*- coding: utf-8 -*-

import heterocl as hcl
import hlib
import time
import numpy as np
import math
from digitrec_data import read_digitrec_data
import os
os.environ["AWS_PLATFORM"] = "xilinx_vcu1525_dynamic_5_1"

N = 7 * 7
max_bit = int(math.ceil(math.log(N, 2)))
data_size = (10, 1800)
test_size = (180,)
hcl.init()

def top(target=None):

    def knn(test_image, train_images):

        def popcount(num):
            out = hcl.scalar(0, "out")
            with hcl.for_(0, train_images.type.bits) as i:
                out.v += num[i]
            return out.v

        # keep sbstituting the max value
        @hcl.def_([(10,1800), (10,3)])
        def update_knn(dist, knn_mat):
            with hcl.for_(0,10, name="i") as i:
                with hcl.for_(0,1800, name="j") as j:
                    max_id = hcl.scalar(0, "max_id")
                    with hcl.for_(0, 3, name="k") as k:
                        with hcl.if_(knn_mat[i][k] > knn_mat[i][max_id.v]):
                            max_id.v = k
                    with hcl.if_(dist[i][j] < knn_mat[i][max_id.v]):
                        knn_mat[i][max_id.v] = dist[i][j]

        diff = hcl.compute(train_images.shape,
                           lambda x, y: train_images[x][y] ^ test_image,
                           "diff")

        dist = hcl.compute(diff.shape,
                           lambda x, y: popcount(diff[x][y]),
                           "dist")

        knn_mat  = hcl.compute((10, 3), lambda x, y: 50, "knn_mat")
        sort_mat = hcl.compute((10, 3), lambda x, y: 50, "sort_mat")

        update_knn(dist, knn_mat)
        hlib.function.sort(knn_mat, sort_mat, axis=1, name="sort_knn")

        return sort_mat

    test_image = hcl.placeholder((), "test_image")
    train_images = hcl.placeholder(data_size, "train_images")
    s = hcl.create_schedule([test_image, train_images], knn)

    diff = knn.diff
    dist = knn.dist
    knn_update = knn.update_knn
    knn_sort   = knn.sort_knn

    s[diff].compute_at(s[dist], dist.axis[1])
    s[knn_update].reorder(knn_update.axis[0], knn_update.axis[1])

    fused = s[knn_update].fuse(knn_update.axis[0], knn_update.axis[1])
    xo, xi = s[knn_update].split(fused, factor=4)
    s[knn_update].pipeline(xi)
    s[knn_update].parallel(xo)

    if target != "llvm": # streaming between kernels
        s.partition(train_images, factor=2)
        tx = s.to(train_images, target.xcel)
        rx = s.to(knn.sort_mat, target.host)
        # s.to(knn.knn_mat, s[knn_sort], s[knn_update], hcl.Stream.FIFO)

    print(hcl.lower(s))
    return hcl.build(s, target=target)

# offload = top("llvm")

tool = hcl.tool.sdaccel
tool.mode = "sw_emu"

target = hcl.platform.aws_f1(tool)
target.xcel.lang = "vhls"
offload = top(target)

def knn_vote(knn_mat):
    knn_score = np.zeros(10)
    for i in range(0, 3):
        min_id = np.argmin(knn_mat, axis = 0)[i]
        knn_score[min_id] += 1
    return np.argmax(knn_score)

train_images, _, test_images, test_labels = read_digitrec_data()
correct = 0.0
total_time = 0
for i in range(0, 10):
    hcl_train_images = hcl.asarray(train_images)
    hcl_knn_mat = hcl.asarray(np.zeros((10, 3)))

    start = time.time()
    offload(test_images[i], hcl_train_images, hcl_knn_mat)
    total_time = total_time + (time.time() - start)

    knn_mat = hcl_knn_mat.asnumpy()
    print(knn_mat)
    if knn_vote(knn_mat) == test_labels[i]:
        correct += 1
        print("match")

print("Average kernel time (s): {:.2f}".format(total_time/180))
print("Accuracy (%): {:.2f}".format(100*correct/180))

assert (correct >= 150.0)
