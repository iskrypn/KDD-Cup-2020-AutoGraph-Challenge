"""the simple baseline for autograph"""
import time

import numpy as np
from ag.system_ext import suppres_all_output
from env_utils import prepare_env
from functools import partial
from sklearn.decomposition import PCA


class Model:
    def __init__(self):
        prepare_env()

        import ray
        ray.init(
            num_gpus=1, num_cpus=4, memory=1e10, object_store_memory=1e10,
            configure_logging=False, ignore_reinit_error=True,
            log_to_driver=True,
            include_webui=False
        )

    def train_predict(self, data, time_budget, n_class, schema):
        start_time = time.time()

        # Make sure imports comes after prepare_env() - pip install
        import torch
        from ag.worker_executor import Executor
        from ag.pyg_model import SEARCH_SPACE_FLAT, PYGModel, create_factory_method
        from ag.pyg_utils import generate_pyg_data

        data = generate_pyg_data(data)
        # x = data.x.numpy()
        # x = PCA(n_components=1300).fit_transform(x)
        # data.x = torch.tensor(x, dtype=torch.float32)

        print('DATAINFO', data, time_budget, n_class)

        base_class = create_factory_method(n_classes=n_class)
        n_edge = data.edge_index.shape[1]
        p_model = Executor(3 if n_edge < 400000 else 1, base_class, data)
        print('CONFIG', len(SEARCH_SPACE_FLAT))

        for config in SEARCH_SPACE_FLAT:
            p_model.apply(config)

        results = []
        while (len(results) != len(SEARCH_SPACE_FLAT)) and ((time.time() - start_time) < (time_budget - 4)):
            r = p_model.get(timeout=2)
            if r is not None:
                results.append(r)

                sresults = list(sorted(results, key=lambda x: -x[0][1]))
                print([r[0][1] for r in sresults[:3]], len(results))

        print('\n'.join([f'{r[0][1]} {r[1]["conv_class"].__name__}' for r in sresults]))
        predictions = np.array([r[0][0] for r in sresults[:2] if r[0][1] > sresults[0][0][1] - 0.02])
        print(predictions.shape)

        from scipy.stats import gmean
        from scipy.special import softmax
        # predictions = predictions.mean(axis=0)
        predictions = np.mean(softmax(predictions, axis=2), axis=0)

        return predictions.argmax(axis=1)

    def __del__(self):
        try:
            with suppres_all_output():
                import ray
                ray.shutdown()
                time.sleep(0.5)
        except:
            pass
