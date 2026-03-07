import re
from bson import ObjectId

class InputValidator:
    @staticmethod
    def validate_string(input_string):
        if not isinstance(input_string, str):
            raise ValueError('Invalid input: must be a string')
        if not input_string.strip():
            raise ValueError('Invalid input: cannot be empty')
        return input_string.strip()

    @staticmethod
    def validate_email(email):
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if not re.match(email_regex, email):
            raise ValueError('Invalid email address')
        return email

    @staticmethod
    def validate_id(value):
        if not ObjectId.is_valid(value):
            raise ValueError('Invalid MongoDB ID')
        return ObjectId(value)

    @staticmethod
    def sanitize_input(input_string):
        return re.sub(r'[<>"&]', '', input_string)  # Remove potentially harmful characters

# Example usage
if __name__ == '__main__':
    try:
        user_input = '<script>alert("hello");</script>'
        safe_input = InputValidator.sanitize_input(user_input)
        print(safe_input)
    except ValueError as e:
        print(e)
