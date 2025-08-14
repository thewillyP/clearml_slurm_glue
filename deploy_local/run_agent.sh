#!/bin/bash
set -euo pipefail

# Get ClearML credentials from AWS Parameter Store
CLEARML_API_ACCESS_KEY=$(docker run --rm \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 amazon/aws-cli \
 ssm get-parameter --name "/dev/research/clearml_api_access_key" --with-decryption --query Parameter.Value --output text)

CLEARML_API_HOST=$(docker run --rm \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 amazon/aws-cli \
 ssm get-parameter --name "/dev/research/clearml_api_host" --query Parameter.Value --output text)

CLEARML_API_SECRET_KEY=$(docker run --rm \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 amazon/aws-cli \
 ssm get-parameter --name "/dev/research/clearml_api_secret_key" --with-decryption --query Parameter.Value --output text)

CLEARML_FILES_HOST=$(docker run --rm \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 amazon/aws-cli \
 ssm get-parameter --name "/dev/research/clearml_files_host" --query Parameter.Value --output text)

CLEARML_WEB_HOST=$(docker run --rm \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 amazon/aws-cli \
 ssm get-parameter --name "/dev/research/clearml_web_host" --query Parameter.Value --output text)

# Run ClearML agent with Docker
docker run -d \
 --name clearml_agent_$(date +%s) \
 -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
 -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
 -e AWS_DEFAULT_REGION=us-east-1 \
 -e CLEARML_API_HOST=${CLEARML_API_HOST} \
 -e CLEARML_WEB_HOST=${CLEARML_WEB_HOST} \
 -e CLEARML_FILES_HOST=${CLEARML_FILES_HOST} \
 -e CLEARML_API_ACCESS_KEY=${CLEARML_API_ACCESS_KEY} \
 -e CLEARML_API_SECRET_KEY=${CLEARML_API_SECRET_KEY} \
 -e CLEARML_AGENT_FORCE_UV=1 \
 thewillyp/clearml-agent \
 clearml-agent daemon --queue infrastructure