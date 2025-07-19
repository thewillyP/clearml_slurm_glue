import os
import subprocess
import tempfile
import boto3
from clearml import Task, TaskTypes, Dataset


def build_and_save_container(docker_url, output_name):
    """Build singularity container from docker image and save as dataset"""

    # Get hostname for SSH
    hostname = subprocess.check_output("hostname", shell=True).decode().strip()

    # Create temporary file for the .sif output
    with tempfile.NamedTemporaryFile(suffix=".sif", delete=False) as tmp_file:
        sif_path = tmp_file.name

    try:
        print(f"[INFO] Building singularity container from {docker_url}")

        # Build the singularity container via SSH - build to tmp, cat, then remove
        remote_tmp_path = "/tmp/container_build.sif"
        build_cmd = (
            f"singularity build -F {remote_tmp_path} {docker_url} && cat {remote_tmp_path} && rm {remote_tmp_path}"
        )
        ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", hostname, build_cmd]

        print(f"[INFO] Running command: ssh {hostname} '{build_cmd}' > {sif_path}")

        # Execute the build command and redirect output to local file
        with open(sif_path, "wb") as output_file:
            result = subprocess.run(ssh_cmd, stdout=output_file, stderr=subprocess.PIPE, check=True)

        # Check if file was created and has content
        if not os.path.exists(sif_path) or os.path.getsize(sif_path) == 0:
            raise RuntimeError("Singularity build failed - no output file created")

        print(f"[INFO] Container built successfully: {sif_path} ({os.path.getsize(sif_path)} bytes)")

        # Create dataset and upload the .sif file
        print(f"[INFO] Creating dataset '{output_name}'")
        dataset = Dataset.create(
            dataset_project="shared",
            dataset_name=output_name,
            description=f"Singularity container built from {docker_url}",
        )

        # Add the .sif file to dataset
        dataset.add_files(sif_path)

        # Finalize and upload
        dataset.upload()
        dataset.finalize()

        print(f"[INFO] Dataset '{output_name}' created with ID: {dataset.id}")
        return dataset.id

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else "Unknown error"
        raise RuntimeError(f"Singularity build failed: {error_msg}")

    finally:
        # Clean up temporary file
        if os.path.exists(sif_path):
            os.unlink(sif_path)
            print(f"[INFO] Cleaned up temporary file: {sif_path}")


def generate_container_name(docker_url):
    """Generate a dataset name from docker URL"""
    # Extract image name and tag from docker URL
    # docker://thewillyp/devenv:cpu -> thewillyp_devenv_cpu
    if docker_url.startswith("docker://"):
        image_part = docker_url[9:]  # Remove docker://
    else:
        image_part = docker_url

    # Replace special characters with underscores
    safe_name = image_part.replace("/", "_").replace(":", "_").replace("-", "_")
    return f"singularity_{safe_name}"


def main():
    # Get task parameters
    task = Task.current_task()

    # Get container configuration
    docker_url = task.get_parameter("container/docker_url")

    print(f"[INFO] Starting container build task")
    print(f"[INFO] Docker URL: {docker_url}")

    # Generate output name from docker URL
    output_name = generate_container_name(docker_url)
    print(f"[INFO] Output dataset name: {output_name}")

    try:
        # Build and save container
        dataset_id = build_and_save_container(docker_url, output_name)

        # Log success
        task.get_logger().report_text(
            f"Successfully built and saved container as dataset '{output_name}' (ID: {dataset_id})"
        )
        print(f"[INFO] Task completed successfully")

    except Exception as e:
        error_msg = f"Container build failed: {str(e)}"
        task.get_logger().report_text(error_msg)
        print(f"[ERROR] {error_msg}")
        raise


if __name__ == "__main__":
    # Initialize AWS credentials from SSM
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

    # Initialize task
    task = Task.init(
        project_name="shared",
        task_name="Container Builder",
        task_type=TaskTypes.data_processing,
    )

    # Create editable parameters
    container_params = {"docker_url": "docker://thewillyp/devenv:cpu"}
    container_params = task.connect(container_params, name="container")

    slurm_params = {
        "memory": "8GB",
        "time": "00:30:00",
        "cpu": 4,
        "gpu": 0,
        "log_dir": "/vast/wlp9800/logs",
        "container_source": {"type": "docker_url", "docker_url": "docker://thewillyp/clearml-agent"},
    }
    slurm_params = task.connect(slurm_params, name="slurm")

    # Execute remotely on slurm queue
    task.execute_remotely(queue_name="slurm", clone=False, exit_process=True)

    # Run the main function
    main()
