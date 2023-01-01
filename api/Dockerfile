FROM python:3.11

# Create app directory
WORKDIR /app

# Install app dependencies
COPY ./requirements.txt ./
RUN pip install -r requirements.txt

# Bundle app source
COPY ./ /app

WORKDIR /app/source

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--reload"]