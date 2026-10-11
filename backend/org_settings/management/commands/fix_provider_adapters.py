from django.core.management.base import BaseCommand
from org_settings.models import AIModelProvider

class Command(BaseCommand):
    help = 'Fixes adapter class names for AI Providers'

    def handle(self, *args, **options):
        self.stdout.write("Starting Adapter Fix...")
        
        mapping = {
            'gemini': 'ai_model.adapters.gemini.GeminiAdapter',
            'deepseek': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            'openai': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            'claude': 'ai_model.adapters.gemini.GeminiAdapter', # Placeholder
        }
        
        for name, adapter in mapping.items():
            try:
                count = AIModelProvider.objects.filter(name=name).update(adapter_class=adapter)
                if count:
                    self.stdout.write(self.style.SUCCESS(f"Updated {name}: set to {adapter}"))
                    
                obj = AIModelProvider.objects.filter(name=name).first()
                if obj:
                    self.stdout.write(f"  -> Verified {name} is: {obj.adapter_class}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error updating {name}: {e}"))
