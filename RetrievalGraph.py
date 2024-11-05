from typing import List

from typing_extensions import TypedDict
import pprint
import os
from langchain import hub
from langchain_core.output_parsers import StrOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain.schema import Document
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_upstage import UpstageGroundednessCheck
from langchain.chains.query_constructor.base import AttributeInfo
from langgraph.graph import END, START, StateGraph
from trulens.apps.langchain import WithFeedbackFilterDocuments
from trulens.core import Feedback, TruSession
from trulens.providers.openai import AzureOpenAI
from trulens.apps.langchain import TruChain
from langchain.load import dumps, loads
UPSTAGE_API_KEY="up_VjWl59uApKL4H69akYmQJNRGEjR2H"


class GradeDocuments(BaseModel):
    """Binary score for relevance check on retrieved documents."""
    binary_score: str = Field(
        description="Documents are relevant to the question, 'yes' or 'no'"
    )


class GraphState(TypedDict):
    """
    Represents the state of our graph.

    Attributes:
        question: question
        generation: LLM generation
        web_search: whether to add search
        documents: list of documents
    """
    crop: str
    question: str
    generation: str
    web_search: str
    documents: List[str]
    groundedness: str

class RetrievalGraph:


    def __init__(self):
        # Initialize Tavily
        self.web_search_tool = TavilySearchResults(k=3)
        self.llm = AzureChatOpenAI(azure_deployment="gpt-4o", 
                                   api_version="2024-05-01-preview", 
                                   azure_endpoint="https://agtech-llm-openai.openai.azure.com",
                                   api_key="5366f9c0121f4852afeb69388c2aff3a")

        # Get access to Chroma vector store that has NC state agriculture information

        #openai_api_key = os.getenv("OPENAI_API_KEY")
        #openai_api_version = "2023-05-15"
        model = "text-embedding-ada-002"
        endpoint = "https://agtech-llm-openai.openai.azure.com"
        api_key = "5366f9c0121f4852afeb69388c2aff3a"
        vector_store_address = os.getenv("AZURE_SEARCH_ENDPOINT")
        vector_store_password = os.getenv("AZURE_SEARCH_ADMIN_KEY")
        print(vector_store_password)
        embeddings: AzureOpenAIEmbeddings = AzureOpenAIEmbeddings(
            api_key=api_key, model=model, azure_endpoint=endpoint
        )
        from langchain_community.vectorstores.azuresearch import AzureSearch
        index_name: str = "crop_guide"

        self.vectorstore = AzureSearch(
            azure_search_endpoint=vector_store_address,
            azure_search_key=vector_store_password,
            index_name=index_name,
            embedding_function=embeddings.embed_query,
        )

        # RAG Chain for checking relevance of retrieved documents
        prompt = hub.pull("rlm/rag-prompt")
        print(prompt)
        self.rag_chain = prompt | self.llm | StrOutputParser()

        # Prompt
        system = """You a question re-writer that converts an input question to a better version that is optimized \n 
                     for web search. Look at the input and try to reason about the underlying semantic intent / meaning."""
        re_write_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                (
                    "human",
                    "Here is the initial question: \n\n {question} \n Formulate an improved question.",
                ),
            ]
        )

        self.question_rewriter = re_write_prompt | self.llm | StrOutputParser()

        workflow = StateGraph(GraphState)

        # Define the nodes
        workflow.add_node("retrieve", self.retrieve)  # retrieve with content relevance score
        workflow.add_node("generate", self.generate)  # generate
        workflow.add_node("transform_query", self.transform_query)  # transform_query
        workflow.add_node("web_search_node", self.web_search)  # web search

        # Build graph
        workflow.add_edge(START, "retrieve")

        workflow.add_conditional_edges(
            "retrieve",
            self.nothing_retrieved,
            {
                "web_search": "web_search_node",
                "generate": "generate",
            },
        )

        workflow.add_edge("web_search_node", "generate")

        workflow.add_conditional_edges(
            "generate",
            self.not_grounded,
            {
                "notGrounded": "transform_query",
                "notSure": "transform_query",
                "grounded": END
            }
        )

        workflow.add_edge("transform_query", "retrieve")

        # Compile
        self.app = workflow.compile()
        pprint.pprint(self.app.get_graph().draw_ascii())

    def invoke(self, question, crop):
        os.environ["LANGCHAIN_TRACING_V2"] = "True"
        os.environ["LANGCHAIN_PROJECT"] = "RetrievalGraph"
        return self.app.invoke({"question": question, "crop": crop})["generation"]


    def retrieve(self, state):

        question = state["question"]
        print(question)
        provider = AzureOpenAI(deployment_name="gpt-4o",
                               api_version="2024-05-01-preview",
                               azure_endpoint="https://agtech-llm-openai.openai.azure.com",
                               api_key="5366f9c0121f4852afeb69388c2aff3a")
        f_context_relevance_score = Feedback(provider.context_relevance)

        retriever = self.vectorstore.as_retriever(search_type="similarity_score_threshold", search_kwargs={"score_threshold":0.75})
        metadata_field_info = [
            AttributeInfo(
                name="crop",
                description="The crop on which the question is asked",
                type="string",
            ),
        ]

        """retriever = SelfQueryRetriever.from_llm(
            llm=self.llm, vectorstore=self.vectorstore, metadata_field_info=metadata_field_info, verbose=True,
            document_contents="information on crops"
        )"""
        filtered_retriever = WithFeedbackFilterDocuments.of_retriever(
            retriever=retriever, feedback=f_context_relevance_score, threshold=0.75
        )


        template = """You are an AI language model assistant. Your task is to break down the larger question
                you get into smaller subquestions to do a vector store retrieval on. 

                Provide a list of subquestions that can be used to search the web for more information.

                Original question: {question}
                Crop: {crop}
                """
        prompt_sub_q = ChatPromptTemplate.from_template(template)

        from langchain_core.output_parsers import StrOutputParser
        from langchain_openai import AzureChatOpenAI

        generate_queries = (
                prompt_sub_q
                | AzureChatOpenAI(azure_deployment="gpt-4o", 
                                     api_version="2024-05-01-preview", 
                                     azure_endpoint="https://agtech-llm-openai.openai.azure.com", 
                                     temperature=0)
                | StrOutputParser()
                | (lambda x: x.split("\n"))
        )

        #retrieval_chain = generate_queries | map(filtered_retriever.get_relevant_documents) | self.get_unique_union
        questions = generate_queries.invoke({"question": question, "crop": state["crop"]})
        print("questions asked ", questions)

        retrieved_docs = []
        for question in questions:
            docs = filtered_retriever.get_relevant_documents(question)
            print("question", question)
            print("docs", docs)
            retrieved_docs.append(docs[:])

        print("retrieved documents ...", retrieved_docs)
        docs = self.get_unique_union(retrieved_docs)

        print("documents retrieved from the vector store are", docs)
        return {"documents": docs}


    def generate(self, state):
        question = state["question"]
        documents = state["documents"]
        provider = AzureChatOpenAI(azure_deployment="gpt-4o",
                                   api_version="2024-05-01-preview",
                                   azure_endpoint="https://agtech-llm-openai.openai.azure.com",
                                   api_key="5366f9c0121f4852afeb69388c2aff3a")
        generation = self.rag_chain.invoke({"context": documents, "question": question})

        groundedness_check = UpstageGroundednessCheck(upstage_api_key='up_VjWl59uApKL4H69akYmQJNRGEjR2H')

        request_input = {
            "context": documents,
            "answer": generation,
        }

        response = groundedness_check.invoke(request_input)
        print("Groundedness response: ", response)
        return {"documents": documents, "question": question, "generation": generation, "groundedness": response}


    def transform_query(self, state):
        """
        Transform the query to produce a better question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates question key with a re-phrased question
        """

        question = state["question"]
        documents = state["documents"]

        # Re-write question
        better_question = self.question_rewriter.invoke({"question": question})
        return {"documents": documents, "question": better_question}


    def get_unique_union(self, documents: list[list]):
        """ Unique union of retrieved docs """
        # Flatten list of lists, and convert each Document to string
        flattened_docs = [dumps(doc) for sublist in documents for doc in sublist]
        # Get unique documents
        unique_docs = list(set(flattened_docs))
        # Return
        return [loads(doc) for doc in unique_docs]


    def web_search(self, state):
        question = state["question"]
        documents = state["documents"]

        template = """You are an AI language model assistant. Your task is to break down the larger question
        you get into smaller subquestions to do a web search on. 
        
        Provide a list of subquestions that can be used to search the web for more information.
        
        Original question: {question}"""
        prompt_sub_q = ChatPromptTemplate.from_template(template)

        from langchain_core.output_parsers import StrOutputParser
        from langchain_openai import AzureChatOpenAI

        generate_queries = (
                prompt_sub_q
                | AzureChatOpenAI(azure_deployment="gpt-4o", 
                                     api_version="2024-05-01-preview", 
                                     azure_endpoint="https://agtech-llm-openai.openai.azure.com", 
                                     temperature=0)
                | StrOutputParser()
                | (lambda x: x.split("\n"))
        )

        retrieval_chain = generate_queries | self.web_search_tool.map() | self.get_unique_union
        docs = retrieval_chain.invoke({"question": question})

        # Web search
        print("Web search for: ", question)
        #docs = self.web_search_tool.invoke({"query": question})
        print(type(docs), docs)

        web_results = "\n".join([d["content"] for d in docs if isinstance(d, dict)])
        web_results = Document(page_content=web_results)
        documents.append(web_results)

        return {"documents": documents, "question": question}


    def nothing_retrieved(self, state):
        documents = state["documents"]
        if len(documents) == 0:
            return "web_search"
        else:
            return "generate"

    def not_grounded(self, state):
        return state["groundedness"]


if __name__ == "__main__":
    graph = RetrievalGraph()
    state = graph.invoke("""
        You are an agricultural pest management expert is a professional with specialized knowledge in entomology, 
        plant pathology, and crop protection.

        A farmer has come to you with a disease effeecting his/her crop. 
        The farmer is growing corn. 
        The farmer has noticed caterpillar insect on the crop.
        His farm's current and next few days weather is sunny.
        His farm's soil moisture is 30. And his irrigation plan is none. 

        You need to provide the farmer with the following information:
        1. Insights on the insect, how it effects the plant and its yield
        2. What factors support insect habitation in your crop field
        3. Now that the insects are present, how to remediate it? Include specific informaiton
            - On what pesticides to use, when to apply given the weather, moisture and irrigation plan
                - explain your reasoning for the timing. Provide reference to the weather and moisture levels and you used it in your reasoning
                - give dates when the pesticides should be applied
            - Where to get the pesticides from
                - Give the websites where the farmer can buy the pesticides
    """, crop="corn")
    print(state)