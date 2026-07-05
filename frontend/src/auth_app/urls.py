from django.urls import path
from . import views

app_name = 'auth_app'

urlpatterns = [
    path('', views.login_view, name='login'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('topics/', views.topics_view, name='topics'),
    path('schedules/', views.schedules_view, name='schedules'),
    path('drafts/', views.drafts_view, name='drafts'),
    path('logout/', views.logout_view, name='logout'),
]
