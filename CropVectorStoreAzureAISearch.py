import os

from langchain_community.vectorstores.azuresearch import AzureSearch
from langchain_openai import AzureOpenAIEmbeddings


#openai_api_key = os.getenv("OPENAI_API_KEY")
azure_deployment="gpt-4o"
api_version="2024-05-01-preview"
azure_endpoint="https://agtech-llm-openai.openai.azure.com"
api_key="5366f9c0121f4852afeb69388c2aff3a"

openai_api_version = "2023-05-15"
model = "text-embedding-ada-002"
vector_store_address = os.getenv("AZURE_SEARCH_ENDPOINT")
vector_store_password = os.getenv("AZURE_SEARCH_ADMIN_KEY")
print(vector_store_password)
embeddings: AzureOpenAIEmbeddings = AzureOpenAIEmbeddings(
    azure_endpoint=azure_endpoint, 
    api_key=api_key, 
    model=model)

index_name: str = "crop_guide"
vector_store: AzureSearch = AzureSearch(
    azure_search_endpoint=vector_store_address,
    azure_search_key=vector_store_password,
    index_name=index_name,
    embedding_function=embeddings.embed_query,
)

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import CharacterTextSplitter

loader = PyPDFLoader("Guides/corn.pdf")
documents = loader.load()
loader = PyPDFLoader("Guides/cotton.pdf")
documents = documents + loader.load()
loader = PyPDFLoader("Guides/soybean.pdf")
documents = documents + loader.load()

for document in documents:
    document.metadata["crop"] = document.metadata["source"].split("/")[1].split(".")[0]

text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
docs = text_splitter.split_documents(documents)

print(len(docs))

vector_store.add_documents(documents=docs)