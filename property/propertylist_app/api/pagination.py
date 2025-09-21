from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination, CursorPagination

class RoomPagination(PageNumberPagination):
  page_size = 2
  page_query_param = 'p'
  page_size_query_param = 'size'
  max_page_size = 3
  last_page_strings = 'end'
  
class RoomLOPagination(LimitOffsetPagination):
    default_limit = 3
    max_limit = 3
    limit_query_param = 'limit'
    offset_query_param = 'start'
    
class RoomCPagination(CursorPagination):
  page_size = 5 
  ordering = 'created'
  cursor_query_param = 'record'
  