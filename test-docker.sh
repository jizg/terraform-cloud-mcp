#!/bin/bash
# Test script for Docker Compose deployment

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Terraform Cloud MCP Server - Docker Test ===${NC}\n"

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Creating .env from .env.docker template..."
    cp .env.docker .env
    echo -e "${YELLOW}Please update .env with your TFC_TOKEN before running${NC}"
    exit 1
fi

# Check if TFC_TOKEN is set
source .env
if [ -z "$TFC_TOKEN" ] || [ "$TFC_TOKEN" = "your-terraform-cloud-token-here" ]; then
    echo -e "${YELLOW}Error: TFC_TOKEN not set in .env file${NC}"
    echo "Please update .env with a valid Terraform Cloud token"
    exit 1
fi

# Menu for test mode selection
echo "Select test mode:"
echo "1) HTTP Mode (Streamable HTTP on port 8000)"
echo "2) stdio Mode (Interactive)"
echo "3) Read-Only HTTP Mode (port 8001)"
echo "4) Stop all containers"
echo "5) View logs"
read -p "Enter choice [1-5]: " choice

case $choice in
    1)
        echo -e "\n${GREEN}Starting MCP Server in Streamable HTTP mode...${NC}"
        docker-compose up --build mcp-http
        ;;
    2)
        echo -e "\n${GREEN}Starting MCP Server in stdio mode...${NC}"
        echo -e "${YELLOW}Note: This is an interactive mode. Use Ctrl+C to exit.${NC}"
        docker-compose run --rm mcp-stdio
        ;;
    3)
        echo -e "\n${GREEN}Starting MCP Server in Read-Only HTTP mode...${NC}"
        docker-compose up --build mcp-http-readonly
        ;;
    4)
        echo -e "\n${GREEN}Stopping all containers...${NC}"
        docker-compose down
        ;;
    5)
        echo -e "\n${GREEN}Available containers:${NC}"
        docker-compose ps -a
        echo ""
        read -p "Enter container name to view logs (or press Enter for all): " container
        if [ -z "$container" ]; then
            docker-compose logs -f
        else
            docker-compose logs -f "$container"
        fi
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
