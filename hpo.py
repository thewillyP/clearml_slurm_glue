from clearml.automation import HyperParameterOptimizer, DiscreteParameterRange, GridSearch
from clearml import Task

# Create optimizer task
opt_task = Task.init(project_name="test", task_name="Grid Search HPO")
opt_task.execute_remotely(queue_name="services", clone=False, exit_process=True)

# Configure optimizer
optimizer = HyperParameterOptimizer(
    base_task_id="0eba363dc3734c4fa19187a140dc528e",
    hyper_parameters=[
        DiscreteParameterRange("hyperparams/batch_size", values=[16, 32, 64]),
        DiscreteParameterRange("hyperparams/learning_rate", values=[0.0001, 0.001, 0.01]),
        DiscreteParameterRange("hyperparams/run_task", values=[True]),
        DiscreteParameterRange("slurm/time", values=["00:45:00"]),
    ],
    objective_metric_title="accuracy",
    objective_metric_series="validation",
    objective_metric_sign="max",
    max_number_of_concurrent_tasks=3,
    optimizer_class=GridSearch,
    execution_queue="slurm",
    total_max_jobs=10,
)

# Start optimization
optimizer.start()
optimizer.wait()
optimizer.stop()
