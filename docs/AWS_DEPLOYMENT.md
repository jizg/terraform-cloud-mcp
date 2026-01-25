# Deploying Terraform Cloud MCP Server to AWS

This guide explains how to deploy the Terraform Cloud MCP Server to AWS using multiple deployment options, including ECS Fargate, App Runner, and AgentCore Runtime.

## Overview

The Terraform Cloud MCP Server supports multiple AWS deployment options:

- **AWS App Runner** (Recommended): Fully managed, simplest deployment, no OAuth required
- **AWS ECS Fargate**: More control over networking and security, no OAuth required
- **AWS AgentCore Runtime**: Fully managed agent runtime with true session isolation, requires OAuth

All deployment options support:
- Session-based authentication (clients provide their own TFC_TOKEN)
- Streamable HTTP transport on port 8000
- Health check endpoint at `/health`
- MCP protocol endpoint at `/mcp`

## Architecture

```
Client Request → AWS Load Balancer → Container (Port 8000) → FastMCP /mcp endpoint → Terraform Cloud API
                    ↓
              Health Check: /health (for monitoring)
```

### Session-Based Authentication Flow

```
1. Client → HTTP POST to /mcp with x-session-id header
2. Client calls set_token() tool with TFC_TOKEN
3. Token stored in session state (isolated by x-session-id)
4. Subsequent calls use session-specific token
5. Each client session is completely isolated
```

## Prerequisites

### Required Tools

1. **AWS CLI** (v2.0+)
   ```bash
   aws --version
   ```

2. **Docker** (v20.10+)
   ```bash
   docker --version
   ```

3. **AWS Account** with appropriate permissions
   - ECS, App Runner, or Bedrock AgentCore access
   - ECR repository creation permissions
   - IAM role creation permissions

### Configure AWS Credentials

```bash
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Enter your region (e.g., us-west-2)
# Enter output format (json)
```

Verify credentials:
```bash
aws sts get-caller-identity
```

## Quick Start (Automated Deployment)

Use the provided `aws-deploy.sh` script for automated deployment:

### Option 1: AWS App Runner (Recommended - Simplest)

```bash
# Deploy to App Runner (no OAuth required, fully managed)
./aws-deploy.sh --app-runner --region us-west-2

# With custom service name
./aws-deploy.sh --app-runner --region us-west-2 --service my-tfc-mcp
```

**Pros:**
- Fully managed, no infrastructure to manage
- Automatic scaling
- Built-in CI/CD with ECR
- No OAuth configuration needed
- Health checks and monitoring included

**Cons:**
- Less control over networking
- AWS-specific (less portable)

### Option 2: AWS ECS Fargate (More Control)

```bash
# Deploy to ECS Fargate (no OAuth required)
./aws-deploy.sh --ecs --region us-west-2

# With custom configuration
./aws-deploy.sh --ecs --region eu-west-1 --service my-tfc-mcp --tag v1.0.0
```

**Pros:**
- Full control over networking and security groups
- VPC integration
- More portable to other container platforms
- No OAuth configuration needed

**Cons:**
- More complex setup
- Requires VPC and subnet configuration

### Option 3: AWS AgentCore Runtime (Fully Managed Agents)

**⚠️ Note:** AgentCore Runtime requires OAuth setup (Cognito or Auth0)

```bash
# Manual setup required - see detailed instructions below
```

**Pros:**
- True session isolation (microVM per session)
- Built-in OAuth authentication
- Designed specifically for MCP servers
- Automatic session management

**Cons:**
- Requires OAuth configuration (Cognito/Auth0)
- More complex initial setup
- AWS Bedrock dependency

## Detailed Deployment Guides

### Option 1: AWS App Runner (Recommended)

#### Step 1: Build and Push Docker Image

```bash
# Set variables
SERVICE_NAME="terraform-cloud-mcp"
AWS_REGION="us-west-2"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create ECR repository
aws ecr create-repository --repository-name "${SERVICE_NAME}" --region "${AWS_REGION}"

# Login to ECR
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build image
docker build -t "${SERVICE_NAME}:latest" .

# Tag image
docker tag "${SERVICE_NAME}:latest" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}:latest"

# Push to ECR
docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}:latest"
```

#### Step 2: Deploy to App Runner

```bash
# Deploy service
aws apprunner create-service \
  --service-name "${SERVICE_NAME}" \
  --source-configuration "RepositoryType=ECR,ImageRepository={ImageIdentifier=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}:latest,ImageRepositoryType=ECR,ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={MCP_TRANSPORT=streamable-http,TFC_ADDRESS=https://app.terraform.io,ENABLE_DELETE_TOOLS=false,READ_ONLY_TOOLS=false}}}" \
  --instance-configuration "Cpu=1 vCPU,Memory=2 GB" \
  --region "${AWS_REGION}"

# Wait for deployment
aws apprunner wait service-active \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}"
```

#### Step 3: Get Service URL

```bash
# Get service URL
SERVICE_URL=$(aws apprunner describe-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Service.ServiceUrl' \
  --output text)

echo "Service deployed successfully!"
echo "Service URL: https://${SERVICE_URL}"
echo "Health endpoint: https://${SERVICE_URL}/health"
echo "MCP endpoint: https://${SERVICE_URL}/mcp"
```

### Option 2: AWS ECS Fargate

#### Step 1: Create ECS Cluster

```bash
# Create ECS cluster
aws ecs create-cluster \
  --cluster-name "${SERVICE_NAME}-cluster" \
  --region "${AWS_REGION}"

# Enable Container Insights
aws ecs update-cluster-settings \
  --cluster "${SERVICE_NAME}-cluster" \
  --settings name=containerInsights,value=enabled \
  --region "${AWS_REGION}"
```

#### Step 2: Create Task Execution Role

```bash
# Create IAM role
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
```

#### Step 3: Create Security Group

```bash
# Create security group (replace VPC_ID with your VPC)
VPC_ID="your-vpc-id"

SECURITY_GROUP_ID=$(aws ec2 create-security-group \
  --group-name "${SERVICE_NAME}-sg" \
  --description "Security group for ${SERVICE_NAME}" \
  --vpc-id "${VPC_ID}" \
  --region "${AWS_REGION}" \
  --query 'GroupId' \
  --output text)

# Allow inbound traffic on port 8000
aws ec2 authorize-security-group-ingress \
  --group-id "$SECURITY_GROUP_ID" \
  --protocol tcp \
  --port 8000 \
  --cidr "0.0.0.0/0" \
  --region "${AWS_REGION}"
```

#### Step 4: Register Task Definition

```bash
# Get task execution role ARN
TASK_EXEC_ROLE_ARN=$(aws iam get-role --role-name "${SERVICE_NAME}-task-execution" --query 'Role.Arn' --output text)

# Register task definition
aws ecs register-task-definition \
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
    "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}:latest",
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
  --region "${AWS_REGION}"
```

#### Step 5: Create ECS Service

```bash
# Get default VPC and subnets
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --region "${AWS_REGION}" --query 'Vpcs[0].VpcId' --output text)

SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=default-for-az,Values=true --region "${AWS_REGION}" --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')

# Create service
aws ecs create-service \
  --cluster "${SERVICE_NAME}-cluster" \
  --service-name "${SERVICE_NAME}" \
  --task-definition "${SERVICE_NAME}" \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=ENABLED}" \
  --region "${AWS_REGION}"
```

### Option 3: AWS AgentCore Runtime

#### Prerequisites

1. **Set up OAuth with AWS Cognito or Auth0**
   
   For Cognito:
   ```bash
   # Use AWS provided script (from documentation)
   ./setup_cognito.sh
   # This provides: DISCOVERY_URL and CLIENT_ID
   ```

   For Auth0:
   ```bash
   # Follow Auth0 setup guide
   # Get: DISCOVERY_URL, CLIENT_ID, and AUDIENCE
   ```

2. **Install AgentCore toolkit**
   ```bash
   pip install bedrock-agentcore-starter-toolkit
   ```

#### Step 1: Configure Deployment

```bash
# Configure AgentCore deployment
agentcore configure -e terraform_cloud_mcp/server.py --protocol MCP

# Interactive prompts:
# - Execution Role: Create/select IAM role
# - ECR Repository: Accept default or specify custom
# - Dependencies: Auto-detected from pyproject.toml
# - OAuth: Enter 'yes', then provide:
#   * Discovery URL (from Cognito/Auth0)
#   * Client ID
#   * Audience (for Auth0)
```

#### Step 2: Deploy to AgentCore

```bash
# Deploy to AWS
agentcore launch

# On success, you'll receive runtime ARN:
# arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/my-runtime
```

#### Step 3: Test Deployment

```bash
# Build endpoint URL (URL-encoded ARN)
AGENT_ARN="arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/my-runtime"
ENCODED_ARN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${AGENT_ARN}', safe=''))")
ENDPOINT="https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT"

echo "MCP Endpoint: ${ENDPOINT}"
echo "Health check not applicable (OAuth protected)"
```

## Testing Your Deployment

### Test Health Endpoint

```bash
# Get service URL (App Runner)
SERVICE_URL=$(aws apprunner describe-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Service.ServiceUrl' \
  --output text)

# Test health endpoint
curl https://${SERVICE_URL}/health

# Expected response:
# {"status": "healthy", "service": "terraform-cloud-mcp", "version": "0.8.20", "timestamp": "..."}
```

### Test MCP Endpoint with MCP Inspector

```bash
# Install MCP Inspector
npx @modelcontextprotocol/inspector

# In the browser, connect to:
# URL: https://<your-service-url>/mcp
# Transport: streamable-http
```

### Test with Python Client

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamablehttp import streamablehttp_client

async def test():
    async with streamablehttp_client("https://<your-service-url>/mcp") as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {len(tools.tools)}")
            
            # Set token
            await session.call_tool("set_token", {"token": "your-tfc-token"})
            
            # List organizations
            result = await session.call_tool("list_organizations", {"page_number": 1, "page_size": 20})
            print(result)

asyncio.run(test())
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `streamable-http` |
| `PORT` | `8000` | Port for HTTP server |
| `HOST` | `0.0.0.0` | Host binding for HTTP server |
| `TFC_ADDRESS` | `https://app.terraform.io` | Terraform Cloud/Enterprise URL |
| `ENABLE_DELETE_TOOLS` | `false` | Enable destructive operations |
| `READ_ONLY_TOOLS` | `false` | Enable only read operations |

### Security Recommendations

#### For Production Deployments:

1. **Use IAM Authentication** (ECS only)
   ```bash
   # Remove public access
   aws ecs update-service \
     --cluster "${SERVICE_NAME}-cluster" \
     --service "${SERVICE_NAME}" \
     --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}"
   ```

2. **Enable Read-Only Mode**
   ```bash
   # Update environment variable
   # For App Runner:
   aws apprunner update-service \
     --service-arn "..." \
     --source-configuration "...,RuntimeEnvironmentVariables={READ_ONLY_TOOLS=true}"
   
   # For ECS:
   # Update task definition with READ_ONLY_TOOLS=true
   ```

3. **Restrict Network Access**
   ```bash
   # Update security group to allow only specific IPs
   aws ec2 update-security-group-rule-descriptions-ingress \
     --group-id "${SECURITY_GROUP_ID}" \
     --ip-permissions "IpProtocol=tcp,FromPort=8000,ToPort=8000,IpRanges=[{CidrIp=10.0.0.0/16,Description=Internal network}]"
   ```

4. **Enable CloudWatch Logging**
   - Already configured in the deployment
   - Monitor logs for security events

5. **Set Resource Limits**
   ```bash
   # For App Runner:
   aws apprunner update-service \
     --service-arn "..." \
     --instance-configuration "Cpu=1 vCPU,Memory=2 GB"
   ```

## Monitoring and Debugging

### View Logs

#### App Runner Logs
```bash
# View logs
aws apprunner describe-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}"

# In AWS Console: App Runner > Services > ${SERVICE_NAME} > Logs
```

#### ECS Logs
```bash
# View logs in real-time
aws logs tail /ecs/${SERVICE_NAME} --follow --region ${AWS_REGION}

# View specific task logs
aws logs filter-log-events \
  --log-group-name /ecs/${SERVICE_NAME} \
  --region ${AWS_REGION} \
  --query 'events[*].message'
```

### Check Service Status

#### App Runner
```bash
aws apprunner describe-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}"
```

#### ECS
```bash
# List tasks
aws ecs list-tasks \
  --cluster "${SERVICE_NAME}-cluster" \
  --service-name "${SERVICE_NAME}" \
  --region "${AWS_REGION}"

# Describe service
aws ecs describe-services \
  --cluster "${SERVICE_NAME}-cluster" \
  --services "${SERVICE_NAME}" \
  --region "${AWS_REGION}"
```

### Update Configuration

#### Update Environment Variables (App Runner)
```bash
aws apprunner update-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --source-configuration "RepositoryType=ECR,ImageRepository={ImageIdentifier=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${SERVICE_NAME}:latest,ImageRepositoryType=ECR,ImageConfiguration={Port=8000,RuntimeEnvironmentVariables={READ_ONLY_TOOLS=true}}}" \
  --region "${AWS_REGION}"
```

#### Update Task Definition (ECS)
```bash
# Register new task definition with updated environment variables
aws ecs register-task-definition \
  --family "${SERVICE_NAME}" \
  # ... (same as before but with updated environment)

# Update service with new task definition
aws ecs update-service \
  --cluster "${SERVICE_NAME}-cluster" \
  --service "${SERVICE_NAME}" \
  --task-definition "${SERVICE_NAME}" \
  --region "${AWS_REGION}"
```

## Troubleshooting

### Container fails to start

**Symptoms:** Service in "Failed" state, health checks failing

**Solutions:**
1. Check CloudWatch logs for errors
2. Verify image exists in ECR
3. Ensure security group allows port 8000
4. Check that PORT environment variable is not overridden

```bash
# View recent logs
aws logs filter-log-events \
  --log-group-name /ecs/${SERVICE_NAME} \
  --region ${AWS_REGION} \
  --query 'events[?contains(message, `ERROR`) || contains(message, `error`)].message'
```

### Health check failures

**Symptoms:** Service stays in "Creating" or "Failed" state

**Solutions:**
1. Test health endpoint manually:
   ```bash
   curl http://<task-ip>:8000/health
   ```

2. Check container logs for startup errors
3. Verify container has curl installed (for ECS health checks)
4. Increase startPeriod in task definition if needed

### Authentication errors

**Symptoms:** "401 Unauthorized" or "Invalid token" errors

**Solutions:**
1. Verify TFC_TOKEN is valid
2. Test token locally first
3. Check Terraform Cloud API access
4. Verify TFC_ADDRESS is correct (for Terraform Enterprise)

```bash
# Test token locally
docker run -e TFC_TOKEN=your-token terraform-cloud-mcp
```

### Session isolation issues

**Symptoms:** Tokens or context bleeding between sessions

**Solutions:**
1. Ensure x-session-id header is being sent
2. Verify FastMCP version >= 3.0.0
3. Check session storage is working
4. Review logs for session ID extraction

```bash
# Test session isolation
# Start two separate clients with different session IDs
# Verify they cannot access each other's tokens
```

## Cost Optimization

### App Runner Costs

App Runner charges based on:
- vCPU usage ($0.064/hour per vCPU)
- Memory usage ($0.007/hour per GB)
- Requests ($0.20 per million requests)

**Cost optimization tips:**
1. **Auto-scaling configuration:**
   ```yaml
   AutoScalingConfiguration:
     MinSize: 1
     MaxSize: 5
     # Scale based on CPU/memory
   ```

2. **Use smaller instance size for development:**
   ```bash
   --instance-configuration "Cpu=0.5 vCPU,Memory=1 GB"
   ```

3. **Enable auto-pause (if applicable):**
   - App Runner doesn't support scale-to-zero
   - Consider ECS with Fargate for scale-to-zero

### ECS Fargate Costs

ECS Fargate charges based on:
- vCPU usage ($0.04048/hour per vCPU)
- Memory usage ($0.004445/hour per GB)

**Cost optimization tips:**
1. **Set minimum tasks to 0:**
   ```bash
   aws ecs update-service \
     --cluster "${SERVICE_NAME}-cluster" \
     --service "${SERVICE_NAME}" \
     --desired-count 0 \
     --region "${AWS_REGION}"
   ```

2. **Right-size tasks:**
   ```bash
   # Start small and adjust based on metrics
   --cpu "256" \
   --memory "512"
   ```

3. **Use Fargate Spot for non-production:**
   ```bash
   --capacity-providers FARGATE_SPOT \
   --default-capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1
   ```

## Comparison: Deployment Options

| Feature | App Runner | ECS Fargate | AgentCore Runtime |
|---------|------------|-------------|-------------------|
| **Setup Complexity** | Low | Medium | High |
| **OAuth Required** | No | No | Yes |
| **Session Isolation** | Container-level | Container-level | MicroVM-level |
| **Scaling** | Auto | Configurable | Auto |
| **Networking Control** | Limited | Full | Limited |
| **Cost** | Pay-per-request | Pay-per-resource | Pay-per-session |
| **Best For** | Prototypes, simple apps | Production, complex networking | Agent platforms |
| **Portability** | AWS-specific | Good (Kubernetes-compatible) | AWS-specific |

## Cleanup

### Remove App Runner Service

```bash
aws apprunner delete-service \
  --service-arn "arn:aws:apprunner:${AWS_REGION}:${AWS_ACCOUNT_ID}:service/${SERVICE_NAME}" \
  --region "${AWS_REGION}"
```

### Remove ECS Service and Resources

```bash
# Delete ECS service
aws ecs delete-service \
  --cluster "${SERVICE_NAME}-cluster" \
  --service "${SERVICE_NAME}" \
  --region "${AWS_REGION}"

# Delete ECS cluster
aws ecs delete-cluster \
  --cluster "${SERVICE_NAME}-cluster" \
  --region "${AWS_REGION}"

# Delete ECR repository
aws ecr delete-repository \
  --repository-name "${SERVICE_NAME}" \
  --region "${AWS_REGION}" \
  --force

# Delete CloudWatch log group
aws logs delete-log-group \
  --log-group-name /ecs/${SERVICE_NAME} \
  --region "${AWS_REGION}"
```

### Remove All Resources (CloudFormation)

If you used the CloudFormation template:

```bash
# Delete CloudFormation stack
aws cloudformation delete-stack \
  --stack-name "${SERVICE_NAME}-stack" \
  --region "${AWS_REGION}"

# Wait for deletion to complete
aws cloudformation wait stack-delete-complete \
  --stack-name "${SERVICE_NAME}-stack" \
  --region "${AWS_REGION}"
```

## Additional Resources

- [AWS App Runner Documentation](https://docs.aws.amazon.com/apprunner/)
- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [AWS Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Terraform Cloud API Documentation](https://developer.hashicorp.com/terraform/cloud-docs/api-docs)

## Support

For issues or questions:
1. Check CloudWatch logs for errors
2. Verify all prerequisites are met
3. Test health endpoint manually
4. Review Terraform Cloud API token validity
5. Check AWS service quotas

## Summary

You now have three deployment options for the Terraform Cloud MCP Server on AWS:

1. **App Runner** - Simplest, fully managed, great for getting started
2. **ECS Fargate** - More control, better for production with complex networking
3. **AgentCore Runtime** - True session isolation, best for agent platforms (requires OAuth)

All options support session-based authentication, making it easy for clients to use their own Terraform Cloud tokens without server-wide secrets.
