#!/bin/bash

# Ensure gh CLI is installed and authenticated
if ! command -v gh &>/dev/null; then
    echo "Error: GitHub CLI (gh) is not installed. Please install it first."
    exit 1
fi

# Define the .env file path
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Could not find $ENV_FILE file."
    exit 1
fi

# Set your GitHub repository details (owner/repo name)
OWNER="YourGitHubUsernameOrOrg"
REPO="YourRepositoryName"
REPO_SLUG="$OWNER/$REPO"

# Process secrets from the .env file
while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip empty lines or comments
    if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
        continue
    fi

    # Extract secret name and value
    if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
        SECRET_NAME="${BASH_REMATCH[1]}"
        SECRET_VALUE="${BASH_REMATCH[2]}"
        # Remove leading/trailing quotes if present
        SECRET_VALUE=$(echo "$SECRET_VALUE" | sed -e 's/^"//' -e 's/"$//')

        echo "Processing secret: $SECRET_NAME"
        # Use the gh CLI to set the secret
        echo -n "$SECRET_VALUE" | gh secret set "$SECRET_NAME" --repo "$REPO_SLUG" -b -
    fi
done <"$ENV_FILE"

echo "All secrets from $ENV_FILE have been processed."
