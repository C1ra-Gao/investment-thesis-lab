FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir gunicorn==23.0.0 && pip install --no-deps .
RUN mkdir -p /app/.local /app/.private && chown -R 10001:10001 /app/.local /app/.private
USER 10001
CMD ["python", "-m", "thesislab.agent_server", "--port", "8767", "--container-local"]
