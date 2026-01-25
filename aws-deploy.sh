#!/bin/bash
# AWS Deployment Script for Terraform Cloud MCP Server
# Supports multiple deployment options: ECS Fargate, App Runner, and AgentCore Runtime

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
SERVICE_NAME="${SERVICE_NAME:-terraform-cloud-mcp}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Terraform Cloud MCP - AWS Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI not found. Please install and configure AWS CLI."
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker."
        exit 1
    fi
    
    # Verify AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Please run 'aws configure' first."
        exit 1
    fi
    
    print_info "Prerequisites check passed!"
}

# Build and push Docker image
build_and_push_image() {
    local registry_type=$1
    print_info "Building Docker image..."
    
    if [ "$registry_type" = "ecr" ]; then
        # ECR Registry
        ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}"
        
        # Create ECR repository if it doesn't exist
        print_info "Creating ECR repository (if it doesn't exist)..."
        aws ecr create-repository --repository-name "${SERVICE_NAME}" --region "${AWS_REGION}" 2>/dev/null || print_warning "Repository may already exist"
        
        # Login to ECR
        print_info "Logging in to ECR..."
        aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REPO}"
        
        # Build image
        docker build -t "${SERVICE_NAME}:${IMAGE_TAG}" .
        
        # Tag and push
        docker tag "${SERVICE_NAME}:${IMAGE_TAG}" "${ECR_REPO}:${IMAGE_TAG}"
        print_info "Pushing image to ECR..."
        docker push "${ECR_REPO}:${IMAGE_TAG}"
        
        echo "${ECR_REPO}:${IMAGE_TAG}"
        
    elif [ "$registry_type" = "dockerhub" ]; then
        # Docker Hub
        if [ -z "$DOCKER_USERNAME" ]; then
            print_error "DOCKER_USERNAME environment variable not set"
            exit 1
        fi
        
        DOCKER_REPO="${DOCKER_USERNAME}/${SERVICE_NAME}"
        
        # Build image
        docker build -t "${SERVICE_NAME}:${IMAGE_TAG}" .
        
        # Tag and push
        docker tag "${SERVICE_NAME}:${IMAGE_TAG}" "${DOCKER_REPO}:${IMAGE_TAG}"
        print_info "Pushing image to Docker Hub..."
        docker push "${DOCKER_REPO}:${IMAGE_TAG}"
        
        echo "${DOCKER_REPO}:${IMAGE_TAG}"
    fi
}

# Deploy to ECS Fargate
deploy_ecs_fargate() {
    print_info "Deploying to ECS Fargate..."
    
    ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}"
    
    # Create ECS cluster if it doesn't exist
    print_info "Creating ECS cluster (if it doesn't exist)..."
    aws ecs create-cluster --cluster-name "${SERVICE_NAME}-cluster" --region "${AWS_REGION}" 2>/dev/null || print_warning "Cluster may already exist"
    
    # Create task execution role if it doesn't exist
    print_info "Creating IAM role for task execution..."
    TASK_EXEC_ROLE_ARN=$(aws iam get-role --role-name "${SERVICE_NAME}-task-execution" --query 'Role.Arn' --output text 2>/dev/null || echo "")
    
    if [ -z "$TASK_EXEC_ROLE_ARN" ]; then
        # Create role
        aws iam create-role \
            --role-name "${SERVICE_NAME}-task-execution" \
            --assume-role-policy-document file://<(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
) \
            --region "${AWS_REGION}"
        
        # Attach execution policy
        aws iam attach-role-policy \
            --role-name "${SERVICE_NAME}-task-execution" \
            --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy \
            --region "${AWS_REGION}"
        
        TASK_EXEC_ROLE_ARN=$(aws iam get-role --role-name "${SERVICE_NAME}-task-execution" --query 'Role.Arn' --output text)
    fi
    
    # Register task definition
    print_info "Registering ECS task definition..."
    TASK_DEFINITION=$(aws ecs register-task-definition \
        --family "${SERVICE_NAME}" \
        --network-mode awsvpc \
        --requires-compatibilities FARGATE \
        --cpu "512" \
        --memory "1024" \
        --execution-role-arn "${TASK_EXEC_ROLE_ARN}" \
        --container-definitions file://<(cat <<EOF
[
  {
    "name": "${SERVICE_NAME}",
    "image": "${ECR_REPO}:${IMAGE_TAG}",
    "portMappings": [
      {
        "containerPort": 8000,
        "protocol": "tcp"
      }
    ],
    "environment": [
      {
        "name": "MCP_TRANSPORT",
        "value": "streamable-http"
      },
      {
        "name": "TFC_ADDRESS",
        "value": "https://app.terraform.io"
      },
      {
        "name": "ENABLE_DELETE_TOOLS",
        "value": "false"
      },
      {
        "name": "READ_ONLY_TOOLS",
        "value": "false"
      }
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/${SERVICE_NAME}",
        "awslogs-region": "${AWS_REGION}",
        "awslogs-stream-prefix": "ecs"
      }
    },
    "healthCheck": {
      "command": [
        "CMD-SHELL",
        "curl -f http://localhost:8000/health || exit 1"
      ],
      "interval": 30,
      "timeout": 5,
      "retries": 3,
      "startPeriod": 60
    }
  }
]
EOF
) \
        --region "${AWS_REGION}" \
        --query 'taskDefinition.taskDefinitionArn' \
        --output text)
    
    # Create security group
    print_info "Creating security group..."
    SECURITY_GROUP_ID=$(aws ec2 create-security-group \
        --group-name "${SERVICE_NAME}-sg" \
        --description "Security group for ${SERVICE_NAME}" \
        --vpc-id "${VPC_ID:-default}" \
        --region "${AWS_REGION}" \
        --query 'GroupId' \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$SECURITY_GROUP_ID" ]; then
        # Allow inbound traffic on port 8000
        aws ec2 authorize-security-group-ingress \
            --group-id "$SECURITY_GROUP_ID" \
            --protocol tcp \
            --port 8000 \
            --cidr "0.0.0.0/0" \
            --region "${AWS_REGION}" 2>/dev/null || print_warning "Rule may already exist"
    else
        SECURITY_GROUP_ID=$(aws ec2 describe-security-groups \
            --filters Name=group-name,Values="${SERVICE_NAME}-sg" \
            --region "${AWS_REGION}" \
            --query 'SecurityGroups[0].GroupId' \
            --output text)
    fi
    
    # Get default VPC and subnets
    if [ -z "$VPC_ID" ]; then
        VPC_ID=$(aws ec2 describe-vpcs \
            --filters Name=isDefault,Values=true \
            --region "${AWS_REGION}" \
            --query 'Vpcs[0].VpcId' \
            --output text)
    fi
    
    SUBNETS=$(aws ec2 describe-subnets \
        --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true \
        --region "${AWS_REGION}" \
        --query 'Subnets[*].SubnetId' \
        --output text | tr '\t' ',')
    
    # Create or update service
    print_info "Creating ECS service..."
    aws ecs create-service \
        --cluster "${SERVICE_NAME}-cluster" \
        --service-name "${SERVICE_NAME}" \
        --task-definition "${TASK_DEFINITION}" \
        --desired-count 1 \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=ENABLED}" \
        --region "${AWS_REGION}" \
        --query 'service.serviceArn' \
        --output text 2>/dev/null || \
    aws ecs update-service \
        --cluster "${SERVICE_NAME}-cluster" \
        --service-name "${SERVICE_NAME}" \
        --task-definition "${TASK_DEFINITION}" \
        --desired-count 1 \
        --region "${AWS_REGION}" \
        --query 'service.serviceArn' \
        --output text
    
    print_info "ECS Fargate deployment complete!"
    print_info "Service will be available at the public IP of the task"
    
    # Get service details
    aws ecs list-tasks --cluster "${SERVICE_NAME}-cluster" --service-name "${SERVICE_NAME}" --region "${AWS_REGION}"
}

# Deploy to App Runner
deploy_app_runner() {
    print_info "Deploying to AWS App Runner..."
    
    ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}"
    
    # Create App Runner service
    print_info "Creating App Runner service..."
    aws apprunner create-service \
        --service-name "${SERVICE_NAME}" \
        --source-configuration "RepositoryType=ECR,ImageRepository={ImageIdentifier=${ECR_REPO}:${IMAGE_TAG},ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={MCP_TRANSPORT=streamable-http,TFC_ADDRESS=https://app.terraform.io,ENABLE_DELETE_TOOLS=false,READ_ONLY_TOOLS=false}}}" \
        --instance-configuration "Cpu=1 vCPU,Memory=2 GB" \
        --region "${AWS_REGION}" \
        --query 'Service.ServiceArn' \
        --output text 2>/dev/null || \
    aws apprunner update-service \
        --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
        --source-configuration "RepositoryType=ECR,ImageRepository={ImageIdentifier=${ECR_REPO}:${IMAGE_TAG},ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={MCP_TRANSPORT=streamable-http,TFC_ADDRESS=https://app.terraform.io,ENABLE_DELETE_TOOLS=false,READ_ONLY_TOOLS=false}}}" \
        --instance-configuration "Cpu=1 vCPU,Memory=2 GB" \
        --region "${AWS_REGION}" \
        --query 'Service.ServiceArn' \
        --output text
    
    print_info "App Runner deployment initiated!"
    print_info "Waiting for service to become active..."
    
    # Wait for service to be active
    aws apprunner wait service-active \
        --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
        --region "${AWS_REGION}" 2>/dev/null || print_warning "Service may still be starting"
    
    # Get service URL
    SERVICE_URL=$(aws apprunner describe-service \
        --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
        --region "${AWS_REGION}" \
        --query 'Service.ServiceUrl' \
        --output text)
    
    print_info "App Runner deployment complete!"
    print_info "Service URL: https://${SERVICE_URL}"
    print_info "MCP endpoint: https://${SERVICE_URL}/mcp"
    print_info "Health check: https://${SERVICE_URL}/health"
}

# Show usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Deploy Terraform Cloud MCP Server to AWS"
    echo ""
    echo "Options:"
    echo "  --ecs              Deploy to ECS Fargate (no OAuth required)"
    echo "  --app-runner       Deploy to App Runner (no OAuth required, simplest)"
    echo "  --agentcore        Deploy to AgentCore Runtime (requires OAuth setup)"
    echo "  --registry TYPE    Container registry: ecr (default) or dockerhub"
    echo "  --region REGION    AWS region (default: us-west-2)"
    echo "  --service NAME     Service name (default: terraform-cloud-mcp)"
    echo "  --tag TAG          Image tag (default: latest)"
    echo "  --help             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --app-runner --region us-east-1"
    echo "  $0 --ecs --region eu-west-1 --service my-tfc-mcp"
    echo "  $0 --app-runner --registry dockerhub"
    echo ""
    echo "Notes:"
    echo "- App Runner is the simplest option (no infrastructure management)"
    echo "- ECS Fargate gives you more control over networking and security"
    echo "- AgentCore Runtime requires OAuth setup via Cognito/Auth0"
    echo "- For Docker Hub, set DOCKER_USERNAME environment variable"
}

# Parse command line arguments
DEPLOYMENT_TYPE=""
REGISTRY_TYPE="ecr"

while [[ $# -gt 0 ]]; do
    case $1 in
        --ecs)
            DEPLOYMENT_TYPE="ecs"
            shift
            ;;
        --app-runner)
            DEPLOYMENT_TYPE="app-runner"
            shift
            ;;
        --agentcore)
            DEPLOYMENT_TYPE="agentcore"
            shift
            ;;
        --registry)
            REGISTRY_TYPE="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --service)
            SERVICE_NAME="$2"
            shift 2
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate deployment type
if [ -z "$DEPLOYMENT_TYPE" ]; then
    print_error "No deployment type specified. Use --ecs, --app-runner, or --agentcore"
    echo ""
    usage
    exit 1
fi

# Main deployment flow
check_prerequisites

# Build and push image
IMAGE_URI=$(build_and_push_image "$REGISTRY_TYPE")
print_info "Image pushed: ${IMAGE_URI}"

# Deploy based on type
case $DEPLOYMENT_TYPE in
    ecs)
        deploy_ecs_fargate
        ;;
    app-runner)
        deploy_app_runner
        ;;
    agentcore)
        print_error "AgentCore Runtime deployment requires OAuth setup."
        print_info "Please refer to AWS_DEPLOYMENT.md for manual setup instructions."
        print_info "Or use --ecs or --app-runner for OAuth-free deployment."
        exit 1
        ;;
esac

print_info "Deployment completed successfully!"
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Next Steps${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "1. Test the deployment:"
echo "   curl https://<your-service-url>/health"
echo ""
echo "2. Connect with MCP client:"
echo "   Use the service URL with /mcp endpoint"
echo ""
echo "3. Set your Terraform Cloud token:"
echo "   Call the set_token tool with your TFC_TOKEN"
echo ""
echo "4. For troubleshooting, check AWS CloudWatch logs"
echo ""
