import azure.functions as func

from src import message

app = func.FunctionApp()


@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(message(), status_code=200)
