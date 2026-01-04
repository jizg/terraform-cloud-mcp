# Deploying Terraform Cloud MCP Server to Google Cloud Run

This guide explains how to deploy the Terraform Cloud MCP Server to Google Cloud Run, enabling it to run in Streamable HTTP (SSE) mode while maintaining support for local stdio mode.

## Prerequisites

1. **Google Cloud Account**: Active GCP account with billing enabled
2. **Google Cloud CLI**: Install [gcloud CLI](https://cloud.google.com/sdk/docs/install)
3. **Docker**: For local testing (optional)
4. **Terraform Cloud Token**: Your TFC API token

## Architecture

The server now supports two transport modes:

- **stdio mode**: For local use with Claude Desktop or CLI
- **streamablehttp mode**: For HTTP-based deployments (Cloud Run, web clients)

The mode is controlled by the `MCP_TRANSPORT` environment variable.

## Setup Instructions

### 1. Initialize Google Cloud Project

```bash
# Set your project ID
export PROJECT_ID="your-project-id"

# Set the project
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  containerregistry.googleapis.com
```

### 2. Store Terraform Cloud Token as Secret

```bash
# Create the secret
echo -n "your-tfc-token-here" | gcloud secrets create TFC_TOKEN \
  --data-file=-

# Grant Cloud Run access to the secret
gcloud secrets add-iam-policy-binding TFC_TOKEN \
  --member="serviceAccount:$(gcloud projects describe $PROJECT_ID \
    --format='value(projectNumber)')-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Deploy Using Cloud Build (Recommended)

The repository includes a `cloudbuild.yaml` configuration that automates building and deployment:

```bash
# Deploy from source
gcloud builds submit --config cloudbuild.yaml

# Or trigger from a Git repository
gcloud builds triggers create github \
  --repo-name=terraform-cloud-mcp \
  --repo-owner=your-github-username \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

### 4. Manual Deployment (Alternative)

If you prefer manual deployment:

```bash
# Build and push the container
gcloud builds submit --tag gcr.io/$PROJECT_ID/terraform-cloud-mcp

# Deploy to Cloud Run
gcloud run deploy terraform-cloud-mcp \
  --image gcr.io/$PROJECT_ID/terraform-cloud-mcp \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars MCP_TRANSPORT=streamablehttp,TFC_ADDRESS=https://app.terraform.io,ENABLE_DELETE_TOOLS=false,READ_ONLY_TOOLS=false \
  --set-secrets TFC_TOKEN=TFC_TOKEN:latest \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 10
```

### 5. Using service.yaml (Declarative)

You can also use the provided `service.yaml` file:

```bash
# Update PROJECT_ID in service.yaml first
sed -i "s/PROJECT_ID/$PROJECT_ID/g" service.yaml

# Deploy the service
gcloud run services replace service.yaml --region us-central1
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `streamablehttp` |
| `PORT` | `8000` | Port for HTTP server (auto-set by Cloud Run) |
| `HOST` | `0.0.0.0` | Host binding for HTTP server |
| `TFC_ADDRESS` | `https://app.terraform.io` | Terraform Cloud/Enterprise URL |
| `TFC_TOKEN` | (required) | Terraform Cloud API token |
| `ENABLE_DELETE_TOOLS` | `false` | Enable destructive operations |
| `READ_ONLY_TOOLS` | `false` | Enable only read operations |

### Security Recommendations

For production deployments:

1. **Use IAM Authentication**: Remove `--allow-unauthenticated` and configure IAM policies
2. **Enable Read-Only Mode**: Set `READ_ONLY_TOOLS=true` for safer operations
3. **Restrict Network**: Use VPC connectors or Serverless VPC Access
4. **Monitor Usage**: Enable Cloud Monitoring and Logging
5. **Set Resource Limits**: Configure memory and CPU limits appropriately

### Enable Authentication

```bash
# Remove public access
gcloud run services remove-iam-policy-binding terraform-cloud-mcp \
  --region us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"

# Grant access to specific users/service accounts
gcloud run services add-iam-policy-binding terraform-cloud-mcp \
  --region us-central1 \
  --member="user:your-email@example.com" \
  --role="roles/run.invoker"
```

## Testing

### Test Locally with Docker

```bash
# Build the image
docker build -t terraform-cloud-mcp .

# Run in stdio mode (default)
docker run -e TFC_TOKEN=your-token terraform-cloud-mcp

# Run in Streamable HTTP mode
docker run -p 8000:8000 \
  -e MCP_TRANSPORT=streamablehttp \
  -e TFC_TOKEN=your-token \
  terraform-cloud-mcp
```

### Test the Deployed Service

```bash
# Get the service URL
SERVICE_URL=$(gcloud run services describe terraform-cloud-mcp \
  --region us-central1 \
  --format 'value(status.url)')

echo "Service URL: $SERVICE_URL"

# Test health endpoint (if implemented)
curl $SERVICE_URL/health

# For Streamable HTTP connection, you can use tools like:
curl -N $SERVICE_URL/sse
```

## Connecting Claude Desktop to Cloud Run

Update your Claude Desktop configuration to use the deployed service:

```json
{
  "mcpServers": {
    "terraform-cloud": {
      "url": "https://your-service-url.run.app",
      "transport": "streamablehttp"
    }
  }
}
```

## Monitoring and Debugging

### View Logs

```bash
# Real-time logs
gcloud run services logs tail terraform-cloud-mcp --region us-central1

# View in Cloud Console
gcloud run services describe terraform-cloud-mcp \
  --region us-central1 \
  --format="value(status.url)"
```

### Check Service Status

```bash
gcloud run services describe terraform-cloud-mcp \
  --region us-central1 \
  --format yaml
```

### Update Configuration

```bash
# Update environment variables
gcloud run services update terraform-cloud-mcp \
  --region us-central1 \
  --set-env-vars READ_ONLY_TOOLS=true

# Update secret
echo -n "new-token" | gcloud secrets versions add TFC_TOKEN --data-file=-
```

## Cost Optimization

Cloud Run charges based on:
- Request count
- CPU and memory usage
- Egress traffic

To optimize costs:

1. **Set minimum instances to 0**: Allows scaling to zero when idle
2. **Configure concurrency**: Set appropriate `containerConcurrency` value
3. **Right-size resources**: Start with minimal CPU/memory and adjust
4. **Use request timeouts**: Set appropriate timeout values

Example cost-optimized configuration:

```bash
gcloud run services update terraform-cloud-mcp \
  --region us-central1 \
  --min-instances 0 \
  --max-instances 5 \
  --concurrency 80 \
  --cpu 0.5 \
  --memory 256Mi \
  --timeout 60
```

## Troubleshooting

### Container fails to start

- Check logs: `gcloud run services logs read terraform-cloud-mcp --region us-central1`
- Verify secrets are accessible
- Ensure PORT environment variable is not overridden

### Authentication errors

- Verify TFC_TOKEN secret contains valid token
- Check secret IAM permissions
- Test token locally first

### Performance issues

- Increase CPU/memory allocation
- Adjust concurrency settings
- Monitor metrics in Cloud Console

## Cleanup

To remove all deployed resources:

```bash
# Delete Cloud Run service
gcloud run services delete terraform-cloud-mcp --region us-central1

# Delete container images
gcloud container images delete gcr.io/$PROJECT_ID/terraform-cloud-mcp --quiet

# Delete secrets
gcloud secrets delete TFC_TOKEN
```

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [FastMCP SSE Transport](https://github.com/jlowin/fastmcp)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Terraform Cloud API Documentation](https://developer.hashicorp.com/terraform/cloud-docs/api-docs)
