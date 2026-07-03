FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY src/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 443

# Prepare for run the application
RUN python src/manage.py makemigrations
RUN python src/manage.py migrate
RUN echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@myproject.com', 'admin')" | python src/manage.py shell

# Run the application with HTTPS
CMD sh -c "mkdir -p /certs && if [ ! -f /certs/localhost.crt ] || [ ! -f /certs/localhost.key ]; then openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes -keyout /certs/localhost.key -out /certs/localhost.crt -subj '/CN=localhost' >/dev/null 2>&1; fi && python src/manage.py runserver_plus --cert-file /certs/localhost.crt --key-file /certs/localhost.key 0.0.0.0:443"