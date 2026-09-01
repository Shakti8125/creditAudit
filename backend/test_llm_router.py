import asyncio
import logging
from app.services.llm.router import LLMRouter

logging.basicConfig(level=logging.INFO)

async def main():
    router = LLMRouter()
    
    print("Testing health checks...")
    nvidia_health = await router.nvidia.health_check()
    print(f"Nvidia Health: {nvidia_health}")
    
    gemini_health = await router.gemini.health_check()
    print(f"Gemini Health: {gemini_health}")
    
    print("\nTesting primary routing...")
    decision = router.get_routing_decision()
    print(f"Initial routing decision: {decision}")
    
    try:
        response = await router.generate("Say hello", temperature=0.0, max_tokens=10)
        print(f"Response: {response}")
    except Exception as e:
        print(f"Generation error: {e}")
        
    print("\nSimulating NVIDIA failure to trip circuit breaker...")
    for _ in range(5):
        router.circuit_breakers["nvidia"].record_failure()
        
    decision = router.get_routing_decision()
    print(f"Routing decision after 5 NVIDIA failures: {decision}")
    
    try:
        response = await router.generate("Say hi from fallback", temperature=0.0, max_tokens=10)
        print(f"Fallback response: {response}")
    except Exception as e:
        print(f"Fallback generation error: {e}")
        
if __name__ == "__main__":
    asyncio.run(main())
