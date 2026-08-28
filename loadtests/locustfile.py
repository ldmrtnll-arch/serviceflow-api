import os

from locust import HttpUser, between, task


class ServiceFlowUser(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        email = os.getenv("LOADTEST_EMAIL", "requester@serviceflow.local")
        password = os.getenv("LOADTEST_PASSWORD", "ServiceFlow123!")
        response = self.client.post(
            "/api/v1/auth/login/",
            json={"email": email, "password": password},
            name="POST /auth/login/",
        )
        if response.ok:
            self.client.headers["Authorization"] = f"Bearer {response.json()['access']}"

    @task(5)
    def list_tickets(self):
        self.client.get("/api/v1/tickets/?page=1", name="GET /tickets/")

    @task(2)
    def current_user(self):
        self.client.get("/api/v1/auth/me/", name="GET /auth/me/")

    @task
    def readiness(self):
        self.client.get("/health/ready/", name="GET /health/ready/")
