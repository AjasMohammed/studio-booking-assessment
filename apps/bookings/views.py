from rest_framework.response import Response
from rest_framework.views import APIView

from .services import book_class


class BookClassAPI(APIView):
    def post(self, request, class_id):
        body, response_status = book_class(
            member=request.user,
            class_session_id=class_id,
            idempotency_key=request.headers.get("Idempotency-Key", "")
        )
        return Response(body, status=response_status)
