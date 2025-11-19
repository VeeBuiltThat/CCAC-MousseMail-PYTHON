class ThreadManager:
    def __init__(self, bot):
        self.bot = bot

    async def create(self, user, message=None):
        # Dummy thread object for testing
        class DummyThread:
            async def send(self, msg):
                pass
        return DummyThread()