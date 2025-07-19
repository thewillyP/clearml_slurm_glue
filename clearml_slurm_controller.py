import os
import subprocess
import time
import boto3
from clearml import Task, TaskTypes, Dataset
from clearml.backend_api.session.client import APIClient

HOSTNAME = subprocess.check_output("hostname", shell=True).decode().strip()


def get_running_slurm_jobs():
    username = subprocess.check_output("whoami", shell=True).decode().strip()
    return int(
        subprocess.check_output(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                HOSTNAME,
                f"squeue --noheader --user {username} | wc -l",
            ]
        )
        .decode()
        .strip()
    )


def resolve_container(task):
    source_type = task.get_parameter("slurm/container_source/type", default="none")

    match source_type:
        case "docker_url":
            return {"type": "docker", "docker_url": task.get_parameter("slurm/container_source/docker_url")}
        case "sif_path":
            return {"type": "sif", "sif_path": task.get_parameter("slurm/container_source/sif_path")}
        case "artifact_task":
            project = task.get_parameter("slurm/container_source/project")
            task_name = task.get_parameter("slurm/container_source/task_name")
            dataset = Dataset.get(dataset_project=project, dataset_name=task_name)
            return {"type": "artifact", "dataset_id": dataset.id}
        case _:
            raise ValueError(f"Invalid container_source/type: {source_type}")


def build_singularity_command(task, task_id):
    container = resolve_container(task)
    gpus = int(task.get_parameter("slurm/gpu", 0))
    use_nv = "--nv" if gpus > 0 else ""

    bind_paths = ["${SLURM_TMPDIR}:/tmp"]
    overlay = task.get_parameter("slurm/singularity_overlay", default="")
    overlay_arg = f"--overlay {overlay}:rw" if overlay else ""

    if not overlay:
        bind_paths.append("${SLURM_TMPDIR}:${HOME}")

    binds = task.get_parameter("slurm/singularity_binds", default="")
    if binds:
        bind_paths.extend(b.strip() for b in binds.split(","))

    bind_arg = f"--bind {','.join(bind_paths)}"
    env_args = (
        "--env AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID "
        "--env AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY "
        "--env AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION "
        "--env CLEARML_TASK_ID=$CLEARML_TASK_ID "
        "--env CLEARML_API_HOST=$CLEARML_API_HOST "
        "--env CLEARML_WEB_HOST=$CLEARML_WEB_HOST "
        "--env CLEARML_FILES_HOST=$CLEARML_FILES_HOST "
        "--env CLEARML_API_ACCESS_KEY=$CLEARML_API_ACCESS_KEY "
        "--env CLEARML_API_SECRET_KEY=$CLEARML_API_SECRET_KEY"
    )

    clearml_cmd = f"clearml-agent execute --id {task_id}"

    match container["type"]:
        case "docker":
            return (
                f"singularity exec {use_nv} --containall --cleanenv {overlay_arg} {bind_arg} {env_args} "
                f"{container['docker_url']} {clearml_cmd}"
            )
        case "sif":
            return (
                f"singularity exec {use_nv} --containall --cleanenv {overlay_arg} {bind_arg} {env_args} "
                f"{container['sif_path']} {clearml_cmd}"
            )
        case "artifact":
            fetch_cmd = (
                "singularity exec --containall --cleanenv --bind $SLURM_TMPDIR "
                "--env AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID "
                "--env AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY "
                "--env AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION "
                "--env CLEARML_API_HOST=$CLEARML_API_HOST "
                "--env CLEARML_WEB_HOST=$CLEARML_WEB_HOST "
                "--env CLEARML_FILES_HOST=$CLEARML_FILES_HOST "
                "--env CLEARML_API_ACCESS_KEY=$CLEARML_API_ACCESS_KEY "
                "--env CLEARML_API_SECRET_KEY=$CLEARML_API_SECRET_KEY "
                "docker://thewillyp/clearml-agent "
                f"clearml-data get --id {container['dataset_id']} --copy $SLURM_TMPDIR/container_dir"
            )

            run_cmd = (
                f"singularity exec {use_nv} --containall --cleanenv {overlay_arg} {bind_arg} {env_args} "
                f"$(find $SLURM_TMPDIR/container_dir -name '*.sif' | head -1) {clearml_cmd}"
            )
            return f"{fetch_cmd} && {run_cmd}"
        case _:
            raise ValueError(f"Unknown container type: {container['type']}")


def create_sbatch_script(task, task_id, singularity_cmd, log_dir):
    gpus = int(task.get_parameter("slurm/gpu", 0))
    gpu_directive = f"#SBATCH --gres=gpu:{gpus}" if gpus > 0 else ""

    return f"""#!/bin/bash
#SBATCH --job-name=clearml_{task.name[:8]}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem={task.get_parameter("slurm/memory")}
#SBATCH --time={task.get_parameter("slurm/time")}
#SBATCH --cpus-per-task={task.get_parameter("slurm/cpu")}
#SBATCH --output={log_dir}/run-%j-{task_id}.log
#SBATCH --error={log_dir}/run-%j-{task_id}.err
{gpu_directive}

export CLEARML_TASK_ID={task_id}
export AWS_ACCESS_KEY_ID="{os.environ["AWS_ACCESS_KEY_ID"]}"
export AWS_SECRET_ACCESS_KEY="{os.environ["AWS_SECRET_ACCESS_KEY"]}"
export AWS_DEFAULT_REGION="{os.environ["AWS_DEFAULT_REGION"]}"
export CLEARML_API_HOST="{os.environ["CLEARML_API_HOST"]}"
export CLEARML_WEB_HOST="{os.environ["CLEARML_WEB_HOST"]}"
export CLEARML_FILES_HOST="{os.environ["CLEARML_FILES_HOST"]}"
export CLEARML_API_ACCESS_KEY="{os.environ["CLEARML_API_ACCESS_KEY"]}"
export CLEARML_API_SECRET_KEY="{os.environ["CLEARML_API_SECRET_KEY"]}"

# Copy SSH directory to SLURM_TMPDIR
mkdir -p ${{SLURM_TMPDIR}}/.ssh
cp -r ${{HOME}}/.ssh/* ${{SLURM_TMPDIR}}/.ssh/
chmod 700 ${{SLURM_TMPDIR}}/.ssh
chmod 600 ${{SLURM_TMPDIR}}/.ssh/*

{singularity_cmd}
"""


def main(controller_task):
    queue_name = controller_task.get_parameter("slurm/queue_name")
    lazy_poll_interval = float(controller_task.get_parameter("slurm/lazy_poll_interval"))
    max_jobs = int(controller_task.get_parameter("slurm/max_jobs"))

    client = APIClient()

    # Get queue ID by name
    queues_response = client.queues.get_all(name=queue_name)
    if not queues_response:
        raise ValueError(f"Queue '{queue_name}' not found")
    queue_id = queues_response[0].id
    print(f"[INFO] Found queue '{queue_name}' with ID: {queue_id}")

    while True:
        try:
            current_jobs = get_running_slurm_jobs()

            if current_jobs >= max_jobs:
                print(f"[INFO] Max jobs ({max_jobs}) reached, sleeping...")
                time.sleep(lazy_poll_interval)
                continue

            # Check how many tasks are in the queue
            num_entries_response = client.queues.get_num_entries(queue=queue_id)
            num_entries = num_entries_response.num

            if num_entries == 0:
                print(f"[INFO] No tasks in queue, lazy polling...")
                time.sleep(lazy_poll_interval)
                continue

            print(f"[INFO] Found {num_entries} tasks in queue, fast polling...")

            # Fast polling loop - dequeue all available tasks
            tasks_processed = 0
            while tasks_processed < num_entries:
                # Check job limit again
                current_jobs = get_running_slurm_jobs()
                if current_jobs >= max_jobs:
                    print(f"[INFO] Hit max jobs limit during burst, processed {tasks_processed}/{num_entries}")
                    break

                print(f"[INFO] Attempting to dequeue task from '{queue_name}'...")
                response = client.queues.get_next_task(queue=queue_id)

                if not response.entry:
                    print(f"[INFO] No more tasks available, processed {tasks_processed}/{num_entries}")
                    break

                task_id = response.entry.task
                task = Task.get_task(task_id=task_id)

                log_dir = task.get_parameter("slurm/log_dir")

                singularity_cmd = build_singularity_command(task, task_id)
                sbatch_script = create_sbatch_script(task, task_id, singularity_cmd, log_dir)

                print(f"[INFO] Submitting SLURM job for task {task_id}")
                subprocess.run(
                    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", HOSTNAME, "sbatch"],
                    input=sbatch_script,
                    text=True,
                )

                tasks_processed += 1

        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(lazy_poll_interval)


if __name__ == "__main__":
    ssm = boto3.client("ssm")

    clearml_api_host = ssm.get_parameter(Name="/dev/research/clearml_api_host")["Parameter"]["Value"]
    clearml_web_host = ssm.get_parameter(Name="/dev/research/clearml_web_host")["Parameter"]["Value"]
    clearml_files_host = ssm.get_parameter(Name="/dev/research/clearml_files_host")["Parameter"]["Value"]
    clearml_access_key = ssm.get_parameter(Name="/dev/research/clearml_api_access_key", WithDecryption=True)[
        "Parameter"
    ]["Value"]
    clearml_secret_key = ssm.get_parameter(Name="/dev/research/clearml_api_secret_key", WithDecryption=True)[
        "Parameter"
    ]["Value"]

    os.environ["CLEARML_API_HOST"] = clearml_api_host
    os.environ["CLEARML_WEB_HOST"] = clearml_web_host
    os.environ["CLEARML_FILES_HOST"] = clearml_files_host
    os.environ["CLEARML_API_ACCESS_KEY"] = clearml_access_key
    os.environ["CLEARML_API_SECRET_KEY"] = clearml_secret_key

    Task.set_credentials(
        api_host=clearml_api_host,
        web_host=clearml_web_host,
        files_host=clearml_files_host,
        key=clearml_access_key,
        secret=clearml_secret_key,
    )

    controller_task = Task.init(
        project_name="slurm_glue",
        task_name="SLURM Controller",
        task_type=TaskTypes.service,
    )

    # Create parameters dict and connect it to task
    params = {"queue_name": "slurm", "max_jobs": 1950, "lazy_poll_interval": 5.0}
    params = controller_task.connect(params, name="slurm")

    controller_task.execute_remotely(queue_name="infrastructure", clone=False, exit_process=True)
    main(controller_task)
