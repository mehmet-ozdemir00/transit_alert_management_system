import hmac
import hashlib
import base64

def generate_secret_hash(username, client_id, client_secret):
    # The message consists of username + client_id
    message = username + client_id
    
    # Create the HMAC-SHA256 hash using the client secret and message
    secret_hash = hmac.new(client_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    
    # Return the base64 encoded result as the SECRET_HASH
    return base64.b64encode(secret_hash.digest()).decode()

# Example usage
username = "mehmet-aws"  # Replace with your username
client_id = "51uoifv8bsa6e3r0md06t9jkqf"  # Your Cognito App Client ID
client_secret = "hocdj4eh35cvhf3qqm3rah9f97ko29k9oubpvkb5fbsi4bkojev"  # Your Cognito App Client Secret

# Generate the SECRET_HASH
secret_hash = generate_secret_hash(username, client_id, client_secret)

# Print the generated SECRET_HASH
print("Generated SECRET_HASH:", secret_hash)