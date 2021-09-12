#!/bin/sh

openssl req \
    -nodes \
    -new \
    -x509 \
    -sha256 \
    -newkey rsa:2048 \
    -keyout key.pem \
    -out cert.pem \
    -days 3650 \
    -subj '/C=GB/ST=London/L=London/O=sensornet/CN=*.sensornet.info/emailAddress=ops@hildebrand.co.uk'
