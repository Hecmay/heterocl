"""
HeteroCL Tutorial : K-means Clustering Algorithm
================================================

**Author**: Yi-Hsiang Lai (seanlatias@github), Ziyan Feng

This is the K-means clustering algorithm written in Heterocl.
"""
import numpy as np
import heterocl as hcl
import time
import random
##############################################################################
# Define the number of the clustering means as K, the number of points as N,
# the number of dimensions as dim, and the number of iterations as niter
K = 16
N = 320
dim = 32
niter = 200

hcl.init()

##############################################################################
# Main Algorithm
# ==============
def top(target=None):
    points = hcl.placeholder((N, dim))
    means = hcl.placeholder((K, dim))

    def kmeans(points, means):
        def loop_kernel(labels):
            # assign cluster
            with hcl.for_(0, N, name="N") as n:
                min_dist = hcl.scalar(100000)
                with hcl.for_(0, K) as k:
                    dist = hcl.scalar(0)
                    with hcl.for_(0, dim) as d:
                        dist_ = hcl.scalar(points[n, d]-means[k, d])
                        dist.v += dist_.v * dist_.v
                    with hcl.if_(dist.v < min_dist.v):
                        min_dist.v = dist.v
                        labels[n] = k
            # update mean
            num_k = hcl.compute((K,), lambda x: 0)
            sum_k = hcl.compute((K, dim), lambda x, y: 0)
            def calc_sum(n):
                num_k[labels[n]] += 1
                with hcl.for_(0, dim) as d:
                    sum_k[labels[n], d] += points[n, d]
            hcl.mutate((N,), lambda n: calc_sum(n), "calc_sum")
            hcl.update(means,
                    lambda k, d: sum_k[k, d]//num_k[k], "update_mean")

        labels = hcl.compute((N,), lambda x: 0, "labels")
        hcl.mutate((niter,), lambda _: loop_kernel(labels), "main_loop")
        return labels

    # create schedule and apply compute customization
    s = hcl.create_schedule([points, means], kmeans)
    main_loop = kmeans.main_loop
    update_mean = main_loop.update_mean
    s[main_loop].pipeline(main_loop.N)
    s[main_loop.calc_sum].unroll(main_loop.calc_sum.axis[0])

    fused = s[update_mean].fuse(update_mean.axis[0], update_mean.axis[1])
    s[update_mean].unroll(fused)
    s.partition(points, hcl.Partition.Cyclic, factor=32)
    s.partition(means, dim=0)
    # s.partition(kmeans.labels, dim=0)
    return hcl.build(s, target=target)

f = top()

points_np = np.random.randint(100, size=(N, dim))
labels_np = np.zeros(N)
means_np = points_np[random.sample(range(N), K), :]

hcl_points = hcl.asarray(points_np, dtype=hcl.Int())
hcl_means = hcl.asarray(means_np, dtype=hcl.Int())
hcl_labels = hcl.asarray(labels_np)

start = time.time()
f(hcl_points, hcl_means, hcl_labels)
total_time = time.time() - start
print("Kernel time (s): {:.2f}".format(total_time))

print("All points:")
print(hcl_points)
print("Final cluster:")
print(hcl_labels)
print("The means:")
print(hcl_means)

from kmeans_golden import kmeans_golden
kmeans_golden(niter, K, N, dim, np.concatenate((points_np,
    np.expand_dims(labels_np, axis=1)), axis=1), means_np)
assert np.allclose(hcl_means.asnumpy(), means_np)
