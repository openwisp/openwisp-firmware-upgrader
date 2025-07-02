from django.shortcuts import render


def test(request):
    return render(request, 'test_app/test.html')
