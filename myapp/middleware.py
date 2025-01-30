import logging
import time

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Логирование информации о запросе
        start_time = time.time()
        logger.info(
            f"Request: {request.method} {request.path}",
            extra={
                "method": request.method,
                "path": request.path,
                "user_agent": request.headers.get("User-Agent", ""),
                "ip": self.get_client_ip(request),
            },
        )

        # Обработка запроса
        response = self.get_response(request)

        # Логирование информации о ответе
        duration = time.time() - start_time
        logger.info(
            f"Response: {request.method} {request.path} - {response.status_code} ({duration:.2f}s)",
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration": duration,
            },
        )

        return response

    def get_client_ip(self, request):
        """
        Получение IP-адреса клиента из запроса.
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip