# ☁️ Deploying the Forgery Detection System on a GCP VM

This guide provides a short, foolproof way to deploy the `forgensic` API, Celery Workers, Redis, and the Frontend onto a standard Google Cloud Platform (GCP) Compute Engine VM. 

Because GCP Linux VMs fully support process forking, this deployment natively uses Celery's `prefork` pool. This completely eliminates the OpenCV thread deadlocks experienced on Windows and handles 500+ concurrent requests beautifully out-of-the-box.

---

## 1. Provision the GCP VM

1. Go to the **Google Cloud Console** > **Compute Engine** > **VM instances**.
2. Click **Create Instance**.
3. **Machine Configuration:** 
   - Choose `e2-standard-4` (4 vCPU, 16 GB memory) or higher. The CPU-bound Computer Vision tasks scale directly with the number of vCPUs.
4. **Boot Disk:** 
   - Choose **Ubuntu 22.04 LTS**.
   - Set disk size to at least `50 GB` (images and models can take space).
5. **Firewall:** 
   - Check **Allow HTTP traffic** and **Allow HTTPS traffic**.

---

## 2. Install Docker and Docker Compose

SSH into your new GCP VM and install the Docker engine:

```bash
# Update packages
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io docker-compose

# Add your user to the docker group (so you don't need 'sudo' for docker commands)
sudo usermod -aG docker $USER

# Log out and log back in for group changes to take effect
exit
```

---

## 3. Clone Your Repository

SSH back into the VM and download your codebase:

```bash
# Clone the repo (replace with your actual git URL)
git clone https://github.com/your-org/TANUH-DPI.git
cd TANUH-DPI
```

---

## 4. Configure Environment Variables

Create a `.env` file in the root of the project to securely store your secrets:

```bash
cat <<EOF > .env
FORGENSIC_SECRET_KEY=generate_a_secure_random_key_here
REDIS_URL=redis://redis:6379/0
OCR_ENABLED=true
PIPELINE_PRESET=npv_focus
EOF
```

---

## 5. Deploy the Stack

We will use the included `docker-compose.yml` file. This spins up the entire architecture (Redis, FastAPI, Celery worker, and Frontend).

Run the stack in detached mode:

```bash
docker-compose up -d --build
```

### What happens now?
- **redis**: Starts a lightweight in-memory queue.
- **forgensic-api**: Starts FastAPI on port `8004`.
- **forgensic-worker**: Starts a Celery worker. Because this is Linux, it automatically uses the `prefork` pool with high concurrency.
- **frontend**: Starts an Nginx server on port `5500` to serve your UI.

---

## 6. Verify the Deployment

Check that all containers are healthy and running without errors:

```bash
# View running containers
docker-compose ps

# View the API logs
docker-compose logs -f forgensic-api

# View the Celery Worker logs (make sure it connected to Redis successfully!)
docker-compose logs -f forgensic-worker
```

---

## 7. Connect Your Domain (Nginx Reverse Proxy)

To expose the services securely via `https://dpi.tanuh.ai`, you should set up an Nginx reverse proxy on the host machine to route traffic to your Docker containers.

1. **Install Nginx:**
   ```bash
   sudo apt-get install -y nginx
   ```
2. **Configure Nginx:** Route `/forgensic/` to `localhost:8004` (API) and `/` to `localhost:5500` (Frontend).
3. **SSL Certificates:** Use **Certbot (Let's Encrypt)** to secure the domain.
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d dpi.tanuh.ai
   ```

You are now fully deployed and ready to handle 500+ requests!
