from django.contrib.auth.models import User
from rest_framework import serializers
from django.core.validators import RegexValidator
from propertylist_app.models import Payment



class RegistrationSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(style={'input_type':'password'}, write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']
        extra_kwargs = {'password': {'write_only': True}}

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate_username(self, value):
        if len(value) < 3 or len(value) > 30:
            raise serializers.ValidationError("Username must be between 3 and 30 characters.")
        RegexValidator(
            regex=r'^[A-Za-z0-9_-]+$',
            message="Username may contain letters, numbers, underscores, and hyphens only."
        )(value)
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    #  Object-level validation 
    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password2'):
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return attrs
    #  END NEW CODE

    def save(self):
        password  = self.validated_data['password']
        account = User(
            email=self.validated_data['email'],
            username=self.validated_data['username']
        )
        account.set_password(password)
        account.save()
        return account
    
    

