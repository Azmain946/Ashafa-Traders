QZ Tray signing files for Ashafa Pharmacy ERP silent printing
================================================================

Files in this folder:
  - digital-certificate.txt   Public certificate (served at /api/qz/certificate/)
  - private-key.pem           Private key (used by /api/qz/sign/ — keep secure)

One-time setup on each pharmacy PC
----------------------------------
1. Install and start QZ Tray (https://qz.io/download/).
2. Open QZ Tray > Advanced > Site Manager.
3. Click + (Add) and browse to this folder's digital-certificate.txt.
4. Set Trust to "Trusted" and save.
5. Add your ERP URL (e.g. http://localhost:8000 or https://your-server) as Allowed.

The web app loads the certificate automatically and signs print requests.

Regenerating keys (optional)
----------------------------
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout private-key.pem \
    -out digital-certificate.txt \
    -days 825 \
    -subj "/CN=Ashafa Traders Pharmacy/O=Ashafa Traders/C=BD"

After regenerating, re-import digital-certificate.txt in QZ Site Manager.
