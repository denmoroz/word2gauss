
import unittest

import numpy as np

from word2gauss.embeddings import GaussianEmbedding, text_to_pairs

DTYPE = np.float32

def sample_embed(energy_type='KL', covariance_type='spherical'):
    mu = np.array([
        [0.0, 0.0],
        [1.0, -1.25],
        [-0.1, -0.4],
        [1.2, -0.3],
        [0.5, 0.5],
        [-0.55, -0.75]
    ], dtype=DTYPE)
    if covariance_type == 'spherical':
        sigma = np.array([
            [1.0],
            [5.0],
            [0.8],
            [0.4],
            [1.5],
            [1.4]
        ], dtype=DTYPE)
    elif covariance_type == 'diagonal':
        sigma = np.array([
            [1.0, 0.1],
            [5.0, 5.5],
            [0.8, 1.1],
            [0.9, 1.9],
            [0.65, 0.9],
            [1.5, 1.55]
        ], dtype=DTYPE)

    return GaussianEmbedding(3, size=2,
        covariance_type=covariance_type,
        energy_type=energy_type,
        mu=mu, sigma=sigma
    )

class TestKLEnergy(unittest.TestCase):
    def test_kl_energy_spherical(self):
        embed = sample_embed(energy_type='KL', covariance_type='spherical')

        # divergence between same distribution is 0
        self.assertAlmostEqual(embed.energy(1, 1), 0.0)

        # energy = -KL divergence
        # 0 is closer to 2 then to 1
        self.assertTrue(-embed.energy(0, 2) < -embed.energy(0, 1))

    def test_kl_energy_diagonal(self):
        embed = sample_embed(energy_type='KL', covariance_type='diagonal')

        # divergence between same distribution is 0
        self.assertAlmostEqual(embed.energy(1, 1), 0.0)

        # energy = -KL divergence
        # 0 is closer to 2 then to 1
        self.assertTrue(-embed.energy(0, 2) < -embed.energy(0, 1))


class TestIPEnergy(unittest.TestCase):
    # energy is log(P(0; mui - muj, Sigmai + Sigmaj)
    # use scipy's multivariate_normal to get true probability
    # then take log

    def test_ip_energy_spherical(self):
        from scipy.stats import multivariate_normal

        embed = sample_embed(energy_type='IP', covariance_type='spherical')

        mui = embed.mu[1, :]
        muj = embed.mu[2, :]
        sigma = np.diag(
            (embed.sigma[1] + embed.sigma[2]) * np.ones(2))
        expected = np.log(multivariate_normal.pdf(
            np.zeros(2), mean=mui - muj, cov=sigma))
        actual = embed.energy(1, 2)
        self.assertAlmostEqual(actual, expected, places=6)

    def test_ip_energy_diagonal(self):
        from scipy.stats import multivariate_normal

        embed = sample_embed(energy_type='IP', covariance_type='diagonal')

        mui = embed.mu[1, :]
        muj = embed.mu[2, :]
        sigma = np.diag(embed.sigma[1, :] + embed.sigma[2, :])
        expected = np.log(multivariate_normal.pdf(
            np.zeros(2), mean=mui - muj, cov=sigma))
        actual = embed.energy(1, 2)
        self.assertAlmostEqual(actual, expected, places=6)


class TestGaussianEmbedding(unittest.TestCase):
    def _training_data(self):
        # 10 words
        # word 0 and 1 co-occur frequently
        # the rest co-occur randomly

        np.random.seed(5)

        # number of sample to do
        nsamples = 100000
        training_data = np.empty((nsamples, 5), dtype=np.uint32)
        for k in xrange(nsamples):
            i = np.random.randint(0, 10)

            # the positive sample
            if i == 0 or i == 1:
                # choose the other 50% of the time
                if np.random.rand() < 0.5:
                    j = 1 - i
                else:
                    j = np.random.randint(0, 10)
            else:
                j = np.random.randint(0, 10)
            pos = (i, j)

            # the negative sample
            neg = (i, np.random.randint(0, 10))
            
            # randomly sample whether left or right is context word
            context_index = np.random.randint(0, 2)

            training_data[k, :] = pos + neg + (context_index, )

        return training_data

    def _check_results(self, embed):
        # should have 0 - 1 close together and 0..1 - 2..9 far apart
        # should also have 2..9 all near each other
        neighbors0 = embed.nearest_neighbors(0, num=10)
        # neighbors[0] is 0
        self.assertEqual(neighbors0[1]['id'], 1)

        # check nearest neighbors to 2, the last two should be 0, 1
        neighbors2 = embed.nearest_neighbors(2, num=10)
        last_two_ids = sorted([result['id'] for result in neighbors2[-2:]])
        self.assertEqual(sorted(last_two_ids), [0, 1])

    def test_model_update(self):
        for covariance_type, sigma_shape1 in [
                ('spherical', 1), ('diagonal', 2)]:
            embed = sample_embed(covariance_type=covariance_type)
            embed.update(5)

            self.assertEquals(embed.mu.shape, (10, 2))
            self.assertEquals(embed.sigma.shape, (10, sigma_shape1))
            self.assertEquals(embed.acc_grad_mu.shape, (10, ))
            self.assertEquals(embed.acc_grad_sigma.shape, (10, ))

            self.assertEquals(embed.N, 5)

    def test_train_batch_KL_spherical(self):
        training_data = self._training_data()

        embed = GaussianEmbedding(10, 5,
            covariance_type='spherical',
            energy_type='KL',
            mu_max=2.0, sigma_min=0.8, sigma_max=1.0, eta=0.1, Closs=1.0
        )

        for k in xrange(0, len(training_data), 100):
            embed.train_batch(training_data[k:(k+100)])

        self._check_results(embed)

    def test_train_batch_KL_diagonal(self):
        training_data = self._training_data()

        embed = GaussianEmbedding(10, 5,
            covariance_type='diagonal',
            energy_type='KL',
            mu_max=2.0, sigma_min=0.8, sigma_max=1.2, eta=0.1, Closs=1.0
        )

        # diagonal training has more parameters so needs more then one
        # epoch to fully learn data
        for k in xrange(0, len(training_data), 100):
            embed.train_batch(training_data[k:(k+100)])

        self._check_results(embed)

    def test_train_batch_IP_spherical(self):
        training_data = self._training_data()

        embed = GaussianEmbedding(10, 5,
            covariance_type='spherical',
            energy_type='IP',
            mu_max=2.0, sigma_min=0.8, sigma_max=1.2, eta=0.1, Closs=1.0
        )

        for k in xrange(0, len(training_data), 100):
            embed.train_batch(training_data[k:(k+100)])

        self._check_results(embed)

    def test_train_batch_IP_diagonal(self):
        training_data = self._training_data()

        embed = GaussianEmbedding(10, 5,
            covariance_type='diagonal',
            energy_type='IP',
            mu_max=2.0, sigma_min=0.8, sigma_max=1.2, eta=0.1, Closs=1.0
        )

        for k in xrange(0, len(training_data), 100):
            embed.train_batch(training_data[k:(k+100)])

        self._check_results(embed)

    def test_train_threads(self):
        training_data = self._training_data()

        embed = GaussianEmbedding(10, 5,
            covariance_type='spherical',
            energy_type='KL',
            mu_max=2.0, sigma_min=0.8, sigma_max=1.2, eta=0.1, Closs=1.0
        )

        def iter_pairs():
            for k in xrange(0, len(training_data), 100):
                yield training_data[k:(k+100)]

        embed.train(iter_pairs(), n_workers=4)

        self._check_results(embed)

class TestTexttoPairs(unittest.TestCase):
    def test_text_to_pairs(self):
        # mock out the random word id generator
        r = lambda N: np.arange(N, dtype=np.uint32)

        # set the seed for the random context size generator
        np.random.seed(55)

        text = [
            np.array([1, 2, 3, -1, 8, 4, 5], dtype=np.uint32),
            np.array([], dtype=np.uint32),
            np.array([10, 11], dtype=np.uint32)
        ]
        actual = text_to_pairs(text, r, nsamples_per_word=2)
        expected = np.array([[ 1,  2,  1,  0,  0],
           [ 1,  2,  1,  1,  0],
           [ 1,  3,  1,  2,  0],
           [ 1,  3,  1,  3,  0],
           [ 1,  2,  4,  2,  1],
           [ 1,  2,  5,  2,  1],
           [ 2,  3,  2,  6,  0],
           [ 2,  3,  2,  7,  0],
           [ 1,  3,  8,  3,  1],
           [ 1,  3,  9,  3,  1],
           [ 2,  3, 10,  3,  1],
           [ 2,  3, 11,  3,  1],
           [ 3,  8,  3, 12,  0],
           [ 3,  8,  3, 13,  0],
           [ 3,  8, 14,  8,  1],
           [ 3,  8, 15,  8,  1],
           [ 8,  4,  8, 16,  0],
           [ 8,  4,  8, 17,  0],
           [ 8,  5,  8, 18,  0],
           [ 8,  5,  8, 19,  0],
           [ 8,  4, 20,  4,  1],
           [ 8,  4, 21,  4,  1],
           [ 4,  5,  4, 22,  0],
           [ 4,  5,  4, 23,  0],
           [ 8,  5, 24,  5,  1],
           [ 8,  5, 25,  5,  1],
           [ 4,  5, 26,  5,  1],
           [ 4,  5, 27,  5,  1],
           [10, 11, 10, 28,  0],
           [10, 11, 10, 29,  0],
           [10, 11, 30, 11,  1],
           [10, 11, 31, 11,  1]], dtype=np.uint32)
        self.assertTrue((actual == expected).all())


if __name__ == '__main__':
    unittest.main()


