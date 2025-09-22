from rest_framework import permissions

class IsAdminOrReadOnly(permissions.IsAdminUser):
  
  
  def has_object_permission(self, request, view, obj):
       if request.method in permissions.SAFE_METHODS:
         return True
       else:
         return bool(request.user and request.user.is_staff)
    
    
    
class IsReviewUserOrReadOnly(permissions.BasePermission):
  
  def has_object_permission(self, request, view, obj):
    if request.method in permissions.SAFE_METHODS:
    # Check permissions for read-only request
        return True
    else:
    # Check permissions for write request
        return obj.review_user==request.user or request.user.is_staff  
      
    #   if request.method in permissions.SAFE_METHODS:
    # return True
    #   If the request is read-only (like GET, HEAD, OPTIONS), allow anyone to access it.
    #   else:
    #       return obj.review_user == request.user or request.user.is_staff
    #   If the request is to edit or delete (PUT, PATCH, DELETE):
    #   Allow only if:
    #   The logged-in user created the review (review_user == request.user), or
    #   The user is an admin/staff (request.user.is_staff)  
    
    

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Read: anyone.
    Write (PUT/PATCH/DELETE): only the room.property_owner or staff.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        owner = getattr(obj, "property_owner", None)
        return (owner is not None and owner == request.user) or bool(request.user and request.user.is_staff)
    