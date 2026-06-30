from waitress import serve
from setup.wsgi import application # Certifique-se que o caminho está correto

if __name__ == '__main__':
    print("Servidor rodando em http://ti-pc02:8000")
    serve(application, host='0.0.0.0', port=8000)