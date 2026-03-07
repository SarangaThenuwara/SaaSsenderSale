# Security Configuration

# This script manages security configurations and validations for the application.

import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

class SecurityConfig:
    def __init__(self):
        self.config = {
            'ENCRYPTION_KEY': os.getenv('ENCRYPTION_KEY', 'default_key'),
            'API_RATE_LIMIT': int(os.getenv('API_RATE_LIMIT', '100')),
            'SECURE_CONNECTIONS': os.getenv('SECURE_CONNECTIONS', 'True') == 'True',
        }

    def validate_config(self):
        # Validate the security configurations
        if not self.config['ENCRYPTION_KEY']:
            logging.error("ENCRYPTION_KEY is not set!")
            return False
        if self.config['API_RATE_LIMIT'] <= 0:
            logging.error("API_RATE_LIMIT must be greater than 0!")
            return False
        logging.info("Security configuration is valid.")
        return True

# Example usage
if __name__ == '__main__':
    security_config = SecurityConfig()
    if security_config.validate_config():
        logging.info("Starting application with valid security configuration.")
    else:
        logging.error("Invalid security configuration. Application startup aborted.")
