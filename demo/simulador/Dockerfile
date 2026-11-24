FROM python:3.12-slim
RUN pip install --no-cache-dir numpy pandas requests
WORKDIR /sim
COPY portal-dados/app/metadados.py portal-dados/testes/simulado.py demo/simulador/simular.py /sim/
CMD ["python", "-u", "/sim/simular.py"]
