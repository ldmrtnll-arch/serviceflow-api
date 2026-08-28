from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView

from config.throttling import LoginRateThrottle, RegisterRateThrottle

from .models import User
from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterRateThrottle]


class LoginView(TokenObtainPairView):
    throttle_classes = [LoginRateThrottle]


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
