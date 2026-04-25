from property.middleware import get_current_request_id

class RequestIDLogFilter:
    def filter(self, record):
        record.request_id = get_current_request_id()
        return True
      