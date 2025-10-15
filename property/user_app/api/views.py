from rest_framework.decorators import api_view  #,  permission_classes
# from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import status
# #from rest_framework_simplejwt.tokens import RefreshToken

from user_app.api.serializers import RegistrationSerializer
from user_app import models


from rest_framework import filters  # if not already imported
from propertylist_app.api.pagination import RoomPagination, RoomCPagination, RoomLOPagination

@api_view(['POST',])
def logout_view(request):
   
   if request.method == 'POST':
     request.user.auth_token.delete()
     return Response(status=status.HTTP_200_OK)



@api_view(['POST'])
#@permission_classes([AllowAny])
def registration_view(request):
  
  
  if request.method =='POST': #only runs if the request is a POST
    serializer = RegistrationSerializer(data=request.data)#Takes the incoming data (from the registration form) and puts it into the RegistrationSerializer for validation and saving
    
    data = {}#Creates an empty dictionary to store the response that will be sent back to the user.
    
    if serializer.is_valid():
        account = serializer.save()
        #return Response(serializer.data)
        
        
        # Checks if all the submitted data is valid (e.g. passwords match, email isn’t already used, etc.).
       #If valid, save the data (i.e., create the new user in the database).
      
      
  #     #Adds a success message and some user details to the response dictionary.
        data['response'] = "Registration Successful!"
        data['username'] = account.username
        data['email'] = account.email
      
        token = Token.objects.get(user=account).key #Gets the authentication token that DRF automatically creates for the user (if TokenAuthentication is used). Adds it to the response.This token will be used for login or future requests.
        data['token'] = token
      
  #     # refresh = RefreshToken.for_user(account)
  #     # data['token'] = {
  #     #         'refresh': str(refresh),
  #     #         'access': str(refresh.access_token),
  #     #     }
      
    else:
       data = serializer.errors#If the data is not valid (e.g. missing fields, bad email, passwords don’t match), store the errors in the response.
      
      
    return Response(data, status=status.HTTP_201_CREATED)#Send the response (success or errors) back to the frontend as JSON.
                      