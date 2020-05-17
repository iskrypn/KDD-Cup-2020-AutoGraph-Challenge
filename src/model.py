"""the simple baseline for autograph"""
import time

from ag.pyg_model import SEARCH_SPACE, PYGModel, create_factory_method
from ag.pyg_utils import generate_pyg_data
from ag.system_ext import suppres_all_output
from env_utils import prepare_env


class Model:
    def __init__(self):
        prepare_env()

        import ray
        ray.init(
            num_gpus=1, num_cpus=4, memory=10e9, object_store_memory=10e9,
            configure_logging=False, ignore_reinit_error=True,
            log_to_driver=True,
            include_webui=False
        )

    def train_predict(self, data, time_budget, n_class, schema):
        start_time = time.time()

        from ag.parametric_family import ParametricFamilyModel

        data = generate_pyg_data(data)
        print('DATAINFO', data, time_budget, n_class)

        input_size = data.x.size()[1]
        base_class = create_factory_method(n_classes=n_class, input_size=input_size)

        p_model = ParametricFamilyModel(
            base_class, SEARCH_SPACE, parallel_predictions=False,
            cpu_per_trial=1, gpu_per_trial=0.3,
        )

        import ray
        data_id = ray.put(data)
        ts = 30 if time_budget < 120 else 60
        p_model.start(data_id, time_budget - ts)
        while (time.time() - start_time) < (time_budget - ts):
            results, n_inc = p_model.executor.get_results()
            if n_inc == 0 and len(results) > 0:
                break
        
        print('\n'.join([f'{x["config"]["conv_class"].__name__} {x}' for x in results]))
        p_model.stop()
        predictions = p_model.predict(data, results, n_top=2)
        return predictions.argmax(axis=1)

    def __del__(self):
        try:
            with suppres_all_output():
                import ray
                ray.shutdown()
                time.sleep(0.5)
        except:
            pass
