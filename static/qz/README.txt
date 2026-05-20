Optional QZ Tray signing files for production silent printing:

1. Generate a certificate/key pair with QZ Tray (Site Manager).
2. Place files here:
   - digital-certificate.txt
   - private-key.pem

The ERP exposes /api/qz/certificate/ and /api/qz/sign/ when these files exist.

Without signing, enable "Allow unsigned requests" in QZ Tray for local development.
