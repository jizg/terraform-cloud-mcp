#!/bin/bash
# Quick deployment script for Google Cloud Run

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    print_error "gcloud CLI is not installed. Please install it from https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Get project ID
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    print_error "No GCP project configured. Run: gcloud config set project PROJECT_ID"
    exit 1
fi

print_info "Using GCP Project: $PROJECT_ID"

# Configuration
SERVICE_NAME="terraform-cloud-mcp"
REGION=${REGION:-"us-central1"}
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

# Parse command line arguments
ENABLE_DELETE=${ENABLE_DELETE_TOOLS:-false}
READ_ONLY=${READ_ONLY_TOOLS:-false}
ALLOW_UNAUTH=${ALLOW_UNAUTH:-true}

print_info "Deployment Configuration:"
echo "  Service Name: $SERVICE_NAME"
echo "  Region: $REGION"
echo "  Enable Delete Tools: $ENABLE_DELETE"
echo "  Read Only Mode: $READ_ONLY"
echo "  Allow Unauthenticated: $ALLOW_UNAUTH"
echo ""

# Check if TFC_TOKEN secret exists
print_info "Checking for TFC_TOKEN secret..."
if ! gcloud secrets describe TFC_TOKEN &>/dev/null; then
    print_warning "TFC_TOKEN secret not found!"
    read -p "Enter your Terraform Cloud API token: " -s TFC_TOKEN
    echo ""
    
    if [ -z "$TFC_TOKEN" ]; then
        print_error "Token cannot be empty"
        exit 1
    fi
    
    print_info "Creating TFC_TOKEN secret..."
    echo -n "$TFC_TOKEN" | gcloud secrets create TFC_TOKEN --data-file=-
    
    # Grant access to compute service account
    PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
    gcloud secrets add-iam-policy-binding TFC_TOKEN \
        --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor"
    
    print_info "Secret created successfully"
else
    print_info "TFC_TOKEN secret found"
fi

# Enable required APIs
print_info "Enabling required Google Cloud APIs..."
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    secretmanager.googleapis.com \
    containerregistry.googleapis.com \
    --quiet

# Build and push container
print_info "Building container image..."
gcloud builds submit --tag $IMAGE_NAME --quiet

# Deploy to Cloud Run
print_info "Deploying to Cloud Run..."

DEPLOY_CMD="gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --region $REGION \
    --platform managed \
    --set-env-vars MCP_TRANSPORT=sse,TFC_ADDRESS=https://app.terraform.io,ENABLE_DELETE_TOOLS=$ENABLE_DELETE,READ_ONLY_TOOLS=$READ_ONLY \
    --set-secrets TFC_TOKEN=TFC_TOKEN:latest \
    --memory 512Mi \
    --cpu 1 \
    --max-instances 10 \
    --min-instances 0 \
    --timeout 300 \
    --quiet"

if [ "$ALLOW_UNAUTH" = "true" ]; then
    DEPLOY_CMD="$DEPLOY_CMD --allow-unauthenticated"
else
    DEPLOY_CMD="$DEPLOY_CMD --no-allow-unauthenticated"
fi

eval $DEPLOY_CMD

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region $REGION \
    --format 'value(status.url)')

print_info "Deployment completed successfully!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Service URL: $SERVICE_URL"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "To view logs:"
echo "  gcloud run services logs tail $SERVICE_NAME --region $REGION"
echo ""
echo "To update configuration:"
echo "  gcloud run services update $SERVICE_NAME --region $REGION --set-env-vars KEY=VALUE"
echo ""

if [ "$ALLOW_UNAUTH" = "true" ]; then
    print_warning "Service is publicly accessible. Consider enabling authentication for production:"
    echo "  gcloud run services remove-iam-policy-binding $SERVICE_NAME \\"
    echo "    --region $REGION \\"
    echo "    --member='allUsers' \\"
    echo "    --role='roles/run.invoker'"
fi
